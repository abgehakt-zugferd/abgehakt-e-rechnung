"""
POST /invoices/{id}/storno als ECHTE Integration (Follow-up zum Audit-#10-Sweep).

Der bisherige Happy-Path (test_storno_router.py) lief gegen _FakeDB und prüfte nur
db.added — db.add() passiert VOR db.commit(), also bliebe der Test grün, wenn der
Commit fehlte. Storno erzeugt eine rechtlich relevante Gutschrift; Persistenz muss
bewiesen sein. Hier: pg_session, Re-Query nach dem Commit.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


def teardown_function():
    app.dependency_overrides.clear()


def _original(pg_session, status="issued", number=None):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=number or f"ALT-2025-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2025, 6, 11), due_date=date(2025, 6, 25), currency="EUR",
                  zugferd_profile="EN16931", tax_category="S", status=status,
                  net_total=Decimal("1000.00"), tax_total=Decimal("190.00"),
                  gross_total=Decimal("1190.00"))
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("10"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("1000.00"),
                             tax_amount=Decimal("190.00"), gross_amount=Decimal("1190.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def test_storno_paid_invoice_persists_credit_note(pg_session):
    """#30: bezahlte Rechnungen sind der häufigere Korrekturfall — der Router
    erlaubt Storno für issued und paid, bisher war nur issued im HTTP→DB-Pfad
    abgedeckt."""
    original = _original(pg_session, "paid")
    r = _client(pg_session).post(f"/invoices/{original.id}/storno")
    assert r.status_code == 303

    pg_session.expire_all()
    storno = (pg_session.query(Invoice)
              .filter(Invoice.original_invoice_id == original.id).first())
    assert storno is not None, "Storno einer bezahlten Rechnung wurde nicht persistiert"
    assert storno.invoice_type == "credit_note"
    assert pg_session.get(Invoice, original.id).status == "paid"


def test_storno_persists_credit_note_and_leaves_original(pg_session):
    original = _original(pg_session, "issued")
    r = _client(pg_session).post(f"/invoices/{original.id}/storno")
    assert r.status_code == 303

    pg_session.expire_all()
    storno = (pg_session.query(Invoice)
              .filter(Invoice.original_invoice_id == original.id).first())
    assert storno is not None, "Storno wurde nicht persistiert (fehlender Commit?)"
    assert storno.invoice_type == "credit_note"
    assert storno.gross_total == Decimal("1190.00")          # positiv (Wirkung via TypeCode 381)
    assert storno.status == "draft"
    assert len(storno.items) == 1
    assert storno.invoice_number != original.invoice_number  # frische fortlaufende Nummer

    original = pg_session.get(Invoice, original.id)
    assert original.status == "issued"                       # Original unverändert
    assert original.invoice_type is None


def test_storno_of_draft_persists_nothing(pg_session):
    original = _original(pg_session, "draft")
    r = _client(pg_session).post(f"/invoices/{original.id}/storno")
    assert r.status_code == 400
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(
        Invoice.original_invoice_id == original.id).first() is None


def test_storno_of_credit_note_is_rejected(pg_session):
    """Eine Gutschrift kann nicht erneut storniert werden → 400 (portiert aus dem
    gelöschten Mock-Test test_storno_router.py, jetzt mit echter DB). Als credit_note
    in EINER Txn angelegt — nachträgliches Setzen an einer issued-Rechnung würde am
    invoice_guard scheitern."""
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    original = Invoice(invoice_number="GS-2025-1", customer_id=c.id,
                       issue_date=date(2025, 6, 11), due_date=date(2025, 6, 25),
                       currency="EUR", zugferd_profile="EN16931", tax_category="S",
                       status="issued", invoice_type="credit_note",
                       net_total=Decimal("1000.00"), tax_total=Decimal("190.00"),
                       gross_total=Decimal("1190.00"))
    pg_session.add(original)
    pg_session.commit()
    r = _client(pg_session).post(f"/invoices/{original.id}/storno")
    assert r.status_code == 400
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(
        Invoice.original_invoice_id == original.id).first() is None


def test_storno_of_unknown_invoice_is_404(pg_session):
    r = _client(pg_session).post(f"/invoices/{uuid.uuid4()}/storno")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Doppel-Storno (#7): pro Original hoechstens EINE Gutschrift.
#
# Der Router prueft heute nur, ob das ORIGINAL selbst eine Gutschrift ist. Ob
# bereits eine Gutschrift auf dieses Original zeigt, prueft niemand. Zwei
# Gutschriften zum selben Beleg ergeben eine doppelte Forderungsminderung: in der
# OPOS-Liste, in der DATEV-Buchung und in der Umsatzsteuervoranmeldung.
#
# Zwei Feinheiten, die die Tests festhalten:
#  - Auch ein noch OFFENER Storno-Entwurf blockiert. Sonst entstuenden zwei
#    Entwuerfe, die beide finalisierbar waeren, und der Fehler faellt erst beim
#    zweiten Finalisieren auf, wenn schon ein Beleg im Archiv liegt.
#  - Ein VERWORFENER Storno blockiert nicht. Sonst gaebe es nach einem Fehlgriff
#    keinen Weg zurueck: der Beleg waere dauerhaft nicht mehr stornierbar.
# ---------------------------------------------------------------------------


def _zaehler(pg_session) -> int:
    from app.models.company import Company
    return pg_session.query(Company).filter(Company.id == 1).one().invoice_counter


def _stornos(pg_session, original) -> list[Invoice]:
    return (pg_session.query(Invoice)
            .filter(Invoice.original_invoice_id == original.id)
            .order_by(Invoice.invoice_number).all())


def test_zweiter_storno_auf_offenen_entwurf_wird_abgewiesen(pg_session):
    original = _original(pg_session, "issued")
    client = _client(pg_session)

    assert client.post(f"/invoices/{original.id}/storno").status_code == 303
    r = client.post(f"/invoices/{original.id}/storno")

    assert r.status_code == 400, r.text
    pg_session.expire_all()
    assert len(_stornos(pg_session, original)) == 1, (
        "Zum selben Original sind zwei Gutschriften entstanden."
    )


def test_zweiter_storno_nach_finalisierung_wird_abgewiesen(pg_session):
    original = _original(pg_session, "issued")
    client = _client(pg_session)

    assert client.post(f"/invoices/{original.id}/storno").status_code == 303
    pg_session.expire_all()
    storno = _stornos(pg_session, original)[0]
    # Nicht durch die Pipeline: hier interessiert nur der Zustand, nicht der Beleg.
    storno.status = "issued"
    pg_session.commit()

    r = client.post(f"/invoices/{original.id}/storno")

    assert r.status_code == 400, r.text
    pg_session.expire_all()
    assert len(_stornos(pg_session, original)) == 1


def test_verworfener_storno_gibt_den_weg_frei(pg_session):
    """Gegenprobe: die Sperre darf keine Sackgasse sein.

    Wer versehentlich storniert und den Entwurf verwirft, muss den Beleg erneut
    stornieren koennen. Sonst waere ein Fehlgriff endgueltig.
    """
    original = _original(pg_session, "issued")
    client = _client(pg_session)

    assert client.post(f"/invoices/{original.id}/storno").status_code == 303
    pg_session.expire_all()
    erster = _stornos(pg_session, original)[0]
    assert client.post(f"/invoices/{erster.id}/verwerfen").status_code == 303

    r = client.post(f"/invoices/{original.id}/storno")

    assert r.status_code == 303, r.text
    pg_session.expire_all()
    offen = [s for s in _stornos(pg_session, original) if s.status != "discarded"]
    assert len(offen) == 1


def test_abgewiesener_zweitstorno_verbraucht_keine_rechnungsnummer(pg_session):
    """Die Pruefung gehoert VOR `generate_next_invoice_number`.

    Der Zaehler auf `Company` wird beim Ziehen der Nummer erhoeht. Eine Ablehnung
    danach liesse eine Nummernluecke ohne jeden Datensatz zurueck, also genau die
    Luecke, die #145 mit dem Status `discarded` vermeiden wollte: unerklaerbar
    gegenueber einer Betriebspruefung.
    """
    original = _original(pg_session, "issued")
    client = _client(pg_session)

    assert client.post(f"/invoices/{original.id}/storno").status_code == 303
    pg_session.expire_all()
    vorher = _zaehler(pg_session)

    assert client.post(f"/invoices/{original.id}/storno").status_code == 400

    pg_session.expire_all()
    assert _zaehler(pg_session) == vorher, (
        "Der abgewiesene Zweitstorno hat eine Rechnungsnummer verbraucht."
    )


# ---------------------------------------------------------------------------
# Der Storno-Entwurf ist nicht bearbeitbar (#8).
#
# `build_storno` kopiert die Betraege 1:1 aus dem Original. Der Entwurf war
# danach aber ueber /bearbeiten frei aenderbar, und der Validator verlangte nur
# eine Originalreferenz, keine Deckung. Eine "Gutschrift zu RE-001" mit anderen
# Betraegen ist buchhalterisch keine Stornierung, sondern eine Teilkorrektur, und
# als solche waere sie ein eigener Belegtyp (384) mit eigenem Weg.
#
# Gesperrt wird die BEARBEITUNGSSEITE, nicht erst das Finalisieren. Wer zehn
# Minuten Positionen aendert und dann eine Fehlermeldung bekommt, hat zehn
# Minuten verloren; die Tuer gehoert davor zu, nicht dahinter.
#
# Die Pruefung im Validator bleibt trotzdem: sie ist die zweite Schicht vor dem
# unwiderruflichen Schreiben ins Archiv, so wie Wachen in der Anwendung und
# Ausloeser in der Datenbank zwei Schichten derselben Zusage sind.
# ---------------------------------------------------------------------------


def _storno_entwurf(pg_session, original):
    _client(pg_session).post(f"/invoices/{original.id}/storno")
    pg_session.expire_all()
    return (pg_session.query(Invoice)
            .filter(Invoice.original_invoice_id == original.id).one())


def test_gutschrift_entwurf_ist_nicht_bearbeitbar(pg_session):
    original = _original(pg_session, "issued")
    storno = _storno_entwurf(pg_session, original)
    r = _client(pg_session).get(f"/invoices/{storno.id}/bearbeiten")
    assert r.status_code == 400, r.text


def test_gutschrift_entwurf_kann_nicht_ueberschrieben_werden(pg_session):
    """Die Sperre muss am POST haengen, nicht nur am Formular. Ein verstecktes
    Formular ist keine Sperre."""
    original = _original(pg_session, "issued")
    storno = _storno_entwurf(pg_session, original)
    vorher = storno.gross_total

    r = _client(pg_session).post(f"/invoices/{storno.id}/bearbeiten", data={})

    assert r.status_code == 400, r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, storno.id).gross_total == vorher


def test_normaler_entwurf_bleibt_bearbeitbar(pg_session):
    """Gegenprobe: die Sperre darf nur Gutschriften treffen."""
    original = _original(pg_session, "draft")
    r = _client(pg_session).get(f"/invoices/{original.id}/bearbeiten")
    assert r.status_code == 200, r.text


def test_detailseite_bietet_bei_gutschrift_kein_bearbeiten(pg_session):
    original = _original(pg_session, "issued")
    storno = _storno_entwurf(pg_session, original)
    client = _client(pg_session)

    seite = client.get(f"/invoices/{storno.id}").text
    assert f"/invoices/{storno.id}/bearbeiten" not in seite, (
        "Die Detailseite der Gutschrift bietet weiterhin einen Bearbeiten-Knopf an."
    )

    # Gegenprobe am normalen Entwurf: sonst bewiese der Test oben nur, dass die
    # Zeichenkette irgendwo fehlt.
    entwurf = _original(pg_session, "draft")  # eigene Nummer, s. Helfer
    assert f"/invoices/{entwurf.id}/bearbeiten" in client.get(f"/invoices/{entwurf.id}").text


def test_abweichende_gutschrift_faellt_im_validator(pg_session):
    """Zweite Schicht vor dem Archiv: Betraege muessen EXAKT dem Original
    entsprechen. Keine Toleranz, denn hier wird nichts gerechnet, sondern kopiert;
    jede Abweichung ist eine Eingabe, keine Rundung."""
    from app.models.company import Company
    from app.services import validator

    original = _original(pg_session, "issued")
    storno = _storno_entwurf(pg_session, original)
    company = pg_session.query(Company).filter(Company.id == 1).one()

    fehler, _ = validator.validate_invoice(storno, company)
    assert not [f for f in fehler if f.code == "STORNO_AMOUNT_MISMATCH"], (
        "Die unveraenderte Gutschrift wurde beanstandet."
    )

    storno.gross_total = original.gross_total - Decimal("0.01")
    fehler, _ = validator.validate_invoice(storno, company)
    codes = [f.code for f in fehler]
    assert "STORNO_AMOUNT_MISMATCH" in codes, codes
