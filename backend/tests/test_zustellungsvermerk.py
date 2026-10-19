"""Zustellung an den Kunden von Hand vermerken (Bauschritt 5b, Teil 2).

Nicht jede Zustellung geht durch dieses Programm: Upload in ein Kundenportal,
Aushändigung, Fax. Der Vermerk ist der Nachweis dafuer, und zwar als Protokoll-
zeile (`ziel='kunde_vermerk'`, ohne Empfaenger) plus `kunde_zugestellt_am` beim
ersten Mal. Ein weiterer Vermerk ist die Korrektur: nichts wird ueberschrieben,
die Detailseite zeigt den juengsten Stand.

Zeitraumgrenzen: Das Datum darf nicht in der Zukunft liegen und nicht vor dem
Ausstellungsdatum — eine Zustellung vor dem Beleg ist keine Zustellung, eine
zukuenftige ist eine Behauptung. Beides ist eine Meldung (400), kein 500er.

SMTP kommt hier nicht vor: Der Vermerk zeichnet einen Vorgang NACH, der ausser-
halb dieses Programms stattfand. Gemailt wird nichts, also gibt es auch nichts
zu attrappieren.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceSendLog
from app.zeit import kalendertag


def teardown_function():
    app.dependency_overrides.clear()


def _seed(pg_session, status="issued", issue=date(2026, 6, 1)):
    """Gestellter Beleg mit Kunde. Ein PDF-Name steht dran, aber fuer den
    Vermerk ist er egal: Der Vorgang lief ausserhalb dieses Programms."""
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München",
                 country="DE", email="kunde@example.de")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-ZV-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=issue, due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status=status,
                  pdf_filename="RE.pdf")
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _logs(pg_session, invoice_id):
    return (pg_session.query(InvoiceSendLog)
            .filter(InvoiceSendLog.invoice_id == invoice_id)
            .order_by(InvoiceSendLog.sent_at).all())


def _vermerken(client, inv, datum="2026-06-10", weg="Upload in das Kundenportal"):
    return client.post(f"/invoices/{inv.id}/zustellung-vermerken",
                       data={"datum": datum, "weg": weg})


# ── Der Vermerk selbst ──────────────────────────────────────────────────────

def test_vermerk_schreibt_protokollzeile_und_setzt_kunde_zugestellt_am(pg_session):
    inv = _seed(pg_session)
    r = _vermerken(_client(pg_session), inv)

    assert r.status_code == 303, r.text
    pg_session.expire_all()
    zeilen = _logs(pg_session, inv.id)
    assert len(zeilen) == 1
    # Der Freitext-Vermerk ist der einzige Weg ohne Empfaenger (DB-CHECK).
    assert zeilen[0].ziel == "kunde_vermerk"
    assert zeilen[0].to_email is None
    assert zeilen[0].weg_notiz == "Upload in das Kundenportal"
    # sent_at traegt das GEWAEHLTE Zustelldatum, nicht den Erfassungszeitpunkt:
    # das Protokoll sortiert nach sent_at, und eine Korrektur mit einem
    # frueheren Zustelldatum muesste sonst obenauf stehen.
    assert kalendertag(zeilen[0].sent_at) == date(2026, 6, 10)
    assert zeilen[0].success is True  # der Nutzer bezeugt die Zustellung
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.kunde_zugestellt_am is not None


def test_zweiter_vermerk_korrigiert_ohne_zu_ueberschreiben(pg_session):
    """Die Korrektur ueberschreibt nichts: alle Protokollzeilen bleiben,
    kunde_zugestellt_am bleibt der Erstvermerk, und die Detailseite zeigt
    den juengsten Stand (Datum und Weg des zweiten Vermerks)."""
    inv = _seed(pg_session)
    c = _client(pg_session)
    assert _vermerken(c, inv, datum="2026-06-10", weg="Upload in das Kundenportal").status_code == 303
    assert _vermerken(c, inv, datum="2026-06-12", weg="Persönlich übergeben").status_code == 303

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    erst = row.kunde_zugestellt_am
    assert erst is not None
    zeilen = _logs(pg_session, inv.id)
    assert len(zeilen) == 2

    seite = c.get(f"/invoices/{inv.id}")
    assert "12.06.2026" in seite.text
    assert "Persönlich übergeben" in seite.text
    # Der erste Vermerk bleibt im Protokoll, verschwindet aber aus der Zeile.
    assert "Kunde: zugestellt am 10.06.2026" not in seite.text


def test_vermerk_nach_standardversand_laesst_erstvermerk_stehen(pg_session):
    """War der Kunde schon per Mail versorgt, ist der spaetere Vermerk nur
    Protokoll: kunde_zugestellt_am bleibt der Zeitpunkt der Mail."""
    inv = _seed(pg_session)
    pg_session.add(InvoiceSendLog(
        invoice_id=inv.id, ziel="kunde_und_buchhaltung", to_email="kunde@example.de",
        sent_at=datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc), success=True,
    ))
    inv.kunde_zugestellt_am = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    pg_session.commit()

    r = _vermerken(_client(pg_session), inv, datum="2026-06-09",
                   weg="Zweitexemplar im Portal")

    assert r.status_code == 303, r.text
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.kunde_zugestellt_am == datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)


# ── Eingaberegeln: Fehler als Meldung, nie als 500er ────────────────────────

def test_vermerk_lehnt_zukuenftiges_datum_ab(pg_session):
    inv = _seed(pg_session)
    r = _vermerken(_client(pg_session), inv, datum="2999-01-01")

    assert r.status_code == 400, r.text
    assert "Zukunft" in r.text
    pg_session.expire_all()
    assert _logs(pg_session, inv.id) == []  # abgelehnt heisst: nichts protokolliert
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.kunde_zugestellt_am is None


def test_vermerk_lehnt_datum_vor_ausstellung_ab(pg_session):
    inv = _seed(pg_session)
    r = _vermerken(_client(pg_session), inv, datum="2026-05-31")

    assert r.status_code == 400, r.text
    assert "Ausstellungsdatum" in r.text
    assert _logs(pg_session, inv.id) == []


def test_vermerk_verlangt_einen_weg(pg_session):
    inv = _seed(pg_session)
    r = _vermerken(_client(pg_session), inv, weg="  ")

    assert r.status_code == 400, r.text
    assert "Weg" in r.text
    assert _logs(pg_session, inv.id) == []


def test_vermerk_lehnt_unlesbares_datum_ab(pg_session):
    inv = _seed(pg_session)
    r = _vermerken(_client(pg_session), inv, datum="nächsten Montag")

    assert r.status_code == 400, r.text
    assert _logs(pg_session, inv.id) == []


def test_vermerk_nur_bei_gestellten_belegen(pg_session):
    inv = _seed(pg_session, status="draft")
    r = _vermerken(_client(pg_session), inv)

    assert r.status_code == 400, r.text
    assert _logs(pg_session, inv.id) == []
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.kunde_zugestellt_am is None


def test_vermerk_unbekannter_beleg_404(pg_session):
    r = _client(pg_session).post(f"/invoices/{uuid.uuid4()}/zustellung-vermerken",
                                 data={"datum": "2026-06-10", "weg": "Portal"})
    assert r.status_code == 404


# ── Detailseite: zwei getrennte Zeilen ───────────────────────────────────────

def test_detailseite_trennt_buchhaltung_und_kunden(pg_session):
    inv = _seed(pg_session)
    seite = _client(pg_session).get(f"/invoices/{inv.id}")
    assert seite.status_code == 200
    assert "Buchhaltung: nicht versendet" in seite.text
    assert "Kunde: nicht versendet" in seite.text

    # Nur an die Buchhaltung: die Kundenzeile bleibt offen.
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    row.datev_sent_at = datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc)
    pg_session.commit()
    seite = _client(pg_session).get(f"/invoices/{inv.id}")
    assert "Buchhaltung: versendet am 02.06.2026" in seite.text
    assert "Kunde: nicht versendet" in seite.text


def test_detailseite_kundenzeile_nennt_den_weg(pg_session):
    """Nach der Mail heisst der Weg „per Mail", nach einem Vermerk der
    Freitext des juengsten Vermerks."""
    inv = _seed(pg_session)
    pg_session.add(InvoiceSendLog(
        invoice_id=inv.id, ziel="kunde_und_buchhaltung", to_email="kunde@example.de",
        sent_at=datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc), success=True,
    ))
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    row.kunde_zugestellt_am = datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc)
    pg_session.commit()
    c = _client(pg_session)

    seite = c.get(f"/invoices/{inv.id}")
    assert "Kunde: zugestellt am 05.06.2026 (per Mail)" in seite.text

    assert _vermerken(c, inv, datum="2026-06-11", weg="Upload in das Kundenportal").status_code == 303
    seite = c.get(f"/invoices/{inv.id}")
    assert "Kunde: zugestellt am 11.06.2026 (Upload in das Kundenportal)" in seite.text


def test_detailseite_zeigt_formular_nur_bei_gestellten_belegen(pg_session):
    inv = _seed(pg_session)
    entwurf = _seed(pg_session, status="draft")
    c = _client(pg_session)

    seite = c.get(f"/invoices/{inv.id}")
    assert "ZUSTELLUNG AN DEN KUNDEN VERMERKEN" in seite.text
    assert 'action="/invoices/' in seite.text and "zustellung-vermerken" in seite.text

    seite = c.get(f"/invoices/{entwurf.id}")
    assert "ZUSTELLUNG AN DEN KUNDEN VERMERKEN" not in seite.text


def test_versandprotokoll_nannt_das_ziel_jeder_zeile(pg_session):
    inv = _seed(pg_session)
    pg_session.add_all([
        InvoiceSendLog(invoice_id=inv.id, ziel="kunde_und_buchhaltung",
                       to_email="kunde@example.de", datev_bcc=True,
                       sent_at=datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc),
                       success=True),
        InvoiceSendLog(invoice_id=inv.id, ziel="buchhaltung", to_email="upload@example.de",
                       sent_at=datetime(2026, 6, 4, 8, 0, tzinfo=timezone.utc), success=True),
    ])
    pg_session.commit()
    assert _vermerken(_client(pg_session), inv, datum="2026-06-10",
                      weg="Upload in das Kundenportal").status_code == 303

    seite = _client(pg_session).get(f"/invoices/{inv.id}")
    assert "Ziel: Kunde und Buchhaltung" in seite.text
    assert "Ziel: Buchhaltung" in seite.text
    assert "Ziel: Kunde (Vermerk)" in seite.text
