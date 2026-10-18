"""Der Auftragsschluessel in der Datenbank (Bauschritt 4a).

Entscheidung 7 und Festlegungen 12/19 aus
docs/specs/rechnungs-und-aufstellungsauftrag.md: Ein Beleg aus einem Auftrag
traegt deren auftragsschluessel als Nachweis und sperrt ihn ueber
auftragsschluessel_offen, solange er weder storniert noch verworfen ist.
Der Status taugt nicht als Kriterium — eine per Stornorechnung aufgehobene
Rechnung bleibt 'issued' oder 'paid' — deshalb die eigene Spalte mit
partiellem Unique-Index.

In diesem Schritt legt noch kein Auftrag einen Beleg an (das kommt in 4b);
die Tests bauen Belege mit Schluessel ueber die Fabriken.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import auftragsschluessel, mustang, pdfa
from app.services.invoice_guard import InvoiceStateError
from app.services.uebergabe_eingang import DatenbankLage
from tests.factories import orm_item, orm_invoice_aus_auftrag

SCHLUESSEL = "plattform:2026-09:kanal-a:x1"
ANDERER_SCHLUESSEL = "plattform:2026-09:kanal-b:y2"


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _beleg(pg_session, schluessel=SCHLUESSEL, *, status="draft", **over):
    """Beleg mit Schluessel aus der Fabrik, committet — der Zustand, in dem ihn
    jeder Leser und jede Route antrifft."""
    inv = orm_invoice_aus_auftrag(
        [orm_item(1, "1", "100.00", "19")], schluessel, status=status, **over
    )
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _frisch(pg_session, inv):
    """Zeile nach einem Routenaufruf neu lesen — die Route committet auf
    derselben Session, und die Assertion soll den Bestand treffen, nicht den
    Zwischenspeicher der Session."""
    pg_session.expire_all()
    return pg_session.query(Invoice).filter(Invoice.id == inv.id).one()


# ── Die eine Stelle: belegen, freigeben, dokument_zu ──────────────────────────

def test_belegen_setzt_nachweis_und_sperre(pg_session):
    inv = _beleg(pg_session)

    assert inv.auftragsschluessel == SCHLUESSEL
    assert inv.auftragsschluessel_offen == SCHLUESSEL


def test_freigeben_leert_nur_die_sperre(pg_session):
    inv = _beleg(pg_session)

    auftragsschluessel.freigeben(inv)
    pg_session.commit()
    inv = _frisch(pg_session, inv)

    assert inv.auftragsschluessel == SCHLUESSEL
    assert inv.auftragsschluessel_offen is None


def test_dokument_zu_nennt_entwurf_oder_nummer(pg_session):
    entwurf = _beleg(pg_session)
    gestellt = _beleg(pg_session, ANDERER_SCHLUESSEL, status="issued")

    assert auftragsschluessel.dokument_zu(pg_session, SCHLUESSEL) == "Entwurf"
    assert auftragsschluessel.dokument_zu(
        pg_session, ANDERER_SCHLUESSEL) == gestellt.invoice_number
    assert auftragsschluessel.dokument_zu(pg_session, "plattform:x") is None


def test_dokument_zu_ignoriert_freigegebene(pg_session):
    """Der Nachweis ohne Sperre ist Archiv, kein Hindernis: Nur
    auftragsschluessel_offen sperrt, der Nachweis allein sperrt nie."""
    inv = _beleg(pg_session)
    auftragsschluessel.freigeben(inv)
    pg_session.commit()

    assert auftragsschluessel.dokument_zu(pg_session, SCHLUESSEL) is None


def test_der_index_verhindert_den_zweiten_beleg_zum_schluessel(pg_session):
    """Der partielle Unique-Index ist die zweite Schicht gegen den Wettlauf
    (Festlegung 19): die Vorabpruefung nimmt keine Sperre, zwei gleichzeitige
    Anfragen saehen beide 'frei'."""
    _beleg(pg_session)

    zweiter = orm_invoice_aus_auftrag(
        [orm_item(1, "1", "50.00", "19")], SCHLUESSEL)
    pg_session.add(zweiter)
    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()


def test_die_sperre_muss_dem_nachweis_gleichen(pg_session):
    """DB-CHECK: auftragsschluessel_offen ist kein freier Wert, sondern
    derselbe wie der Nachweis — oder NULL. Der CHECK schlaegt beim UPDATE
    selbst zu, nicht erst beim Commit."""
    inv = _beleg(pg_session)
    with pytest.raises(IntegrityError):
        pg_session.execute(
            Invoice.__table__.update()
            .where(Invoice.id == inv.id)
            .values(auftragsschluessel_offen="fremd:key")
        )
    pg_session.rollback()


# ── Leser (§ 8a: erhalten nennt die Nummer oder 'Entwurf') ────────────────────

def test_datenbanklage_liefert_entwurf_ueber_die_sperrende_spalte(pg_session):
    entwurf = _beleg(pg_session)

    lage = DatenbankLage(pg_session)
    assert lage.dokument_zu_auftragsschluessel(SCHLUESSEL) == "Entwurf"
    assert lage.dokument_zu_auftragsschluessel("plattform:x") is None


def test_datenbanklage_liefert_die_nummer_eines_gestellten_belegs(pg_session):
    gestellt = _beleg(pg_session, status="issued")

    assert DatenbankLage(
        pg_session).dokument_zu_auftragsschluessel(SCHLUESSEL) == gestellt.invoice_number


def test_datenbanklage_sieht_einen_freigegebenen_schluessel_als_frei(pg_session):
    inv = _beleg(pg_session)
    auftragsschluessel.freigeben(inv)
    pg_session.commit()

    assert DatenbankLage(pg_session).dokument_zu_auftragsschluessel(SCHLUESSEL) is None


# ── Guard: nach dem Finalisieren nur noch leeren ─────────────────────────────

def test_guard_leeren_der_sperre_nach_finalisieren_erlaubt(pg_session):
    inv = _beleg(pg_session, status="issued")

    auftragsschluessel.freigeben(inv)
    pg_session.commit()

    assert _frisch(pg_session, inv).auftragsschluessel_offen is None


def test_guard_setzen_der_sperre_nach_finalisieren_verboten(pg_session):
    inv = _beleg(pg_session, status="issued")
    auftragsschluessel.freigeben(inv)
    pg_session.commit()

    auftragsschluessel.belegen(inv, SCHLUESSEL)
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_guard_aendern_der_sperre_nach_finalisieren_verboten(pg_session):
    inv = _beleg(pg_session, status="issued")

    inv.auftragsschluessel_offen = ANDERER_SCHLUESSEL
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_guard_nachweis_nach_finalisieren_unveraenderlich(pg_session):
    inv = _beleg(pg_session, status="issued")

    inv.auftragsschluessel = ANDERER_SCHLUESSEL
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_entwurf_darf_die_sperre_noch_setzen(pg_session):
    """Vor dem Finalisieren gibt es keine Sperre: Verwerfen und Zurueckholen
    brauchen beides freie Hand, sonst waere ein Fehlgriff endgueltig."""
    inv = _beleg(pg_session, status="discarded")
    inv.auftragsschluessel_offen = None
    pg_session.commit()

    auftragsschluessel.belegen(inv, SCHLUESSEL)
    pg_session.commit()

    assert _frisch(pg_session, inv).auftragsschluessel_offen == SCHLUESSEL


# ── Verwerfen (Freigabe) ──────────────────────────────────────────────────────

def test_verwerfen_gibt_den_schluessel_frei(pg_session):
    inv = _beleg(pg_session)

    r = _client(pg_session).post(f"/invoices/{inv.id}/verwerfen")

    assert r.status_code == 303
    inv = _frisch(pg_session, inv)
    assert inv.status == "discarded"
    assert inv.auftragsschluessel == SCHLUESSEL
    assert inv.auftragsschluessel_offen is None


# ── Manuelles Stornieren (Freigabe) ───────────────────────────────────────────

def test_manuelles_stornieren_gibt_den_schluessel_frei(pg_session):
    inv = _beleg(pg_session, status="issued")

    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status", data={"new_status": "cancelled"})

    assert r.status_code == 303
    inv = _frisch(pg_session, inv)
    assert inv.status == "cancelled"
    assert inv.auftragsschluessel == SCHLUESSEL
    assert inv.auftragsschluessel_offen is None


def test_bezahlt_bleibt_bei_der_zahlung(pg_session):
    """Nur Stornieren und Verwerfen geben frei — bezahlen nicht: Der Beleg
    besteht ja weiter."""
    inv = _beleg(pg_session, status="issued")

    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status",
        data={"new_status": "paid", "bezahlt_am": "2026-09-30"})

    assert r.status_code == 303
    assert _frisch(pg_session, inv).auftragsschluessel_offen == SCHLUESSEL


# ── Zurueckholen (Festlegung 19) ─────────────────────────────────────────────

def _verworfen(pg_session, schluessel=SCHLUESSEL):
    inv = _beleg(pg_session, schluessel)
    r = _client(pg_session).post(f"/invoices/{inv.id}/verwerfen")
    assert r.status_code == 303
    return _frisch(pg_session, inv)


def test_zurueckholen_besetzt_den_schluessel_wieder(pg_session):
    inv = _verworfen(pg_session)

    r = _client(pg_session).post(f"/invoices/{inv.id}/zurueckholen")

    assert r.status_code == 303
    inv = _frisch(pg_session, inv)
    assert inv.status == "draft"
    assert inv.auftragsschluessel == SCHLUESSEL
    assert inv.auftragsschluessel_offen == SCHLUESSEL
    assert auftragsschluessel.dokument_zu(pg_session, SCHLUESSEL) == "Entwurf"


def test_zurueckholen_ohne_schluessel_bleibt_wie_vorher(pg_session):
    """Belege ohne Auftragsschluessel (die bisherigen) nehmen am Sperrtest
    nicht teil — ihr Zurueckholen aendert sich nicht."""
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-4A-{uuid.uuid4().hex[:6]}",
                  customer_id=c.id, issue_date=date(2026, 6, 1),
                  due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status="discarded")
    pg_session.add(inv)
    pg_session.commit()

    r = _client(pg_session).post(f"/invoices/{inv.id}/zurueckholen")

    assert r.status_code == 303
    assert _frisch(pg_session, inv).status == "draft"


def test_zurueckholen_wird_abgelehnt_wenn_der_schluessel_belegt_ist(pg_session):
    inv = _verworfen(pg_session)
    anderer = _beleg(pg_session, SCHLUESSEL, status="issued",
                     invoice_number="RE-4A-STOERT")

    r = _client(pg_session).post(f"/invoices/{inv.id}/zurueckholen")

    assert r.status_code == 400
    assert ("Zu diesem Auftrag gibt es inzwischen einen anderen Beleg: "
            f"{anderer.invoice_number}") in r.text
    inv = _frisch(pg_session, inv)
    assert inv.status == "discarded"
    assert inv.auftragsschluessel_offen is None


def test_zurueckholen_ablehnung_nennt_auch_einen_entwurf(pg_session):
    inv = _verworfen(pg_session)
    _beleg(pg_session, SCHLUESSEL, invoice_number="RE-4A-ENTWURF")

    r = _client(pg_session).post(f"/invoices/{inv.id}/zurueckholen")

    assert r.status_code == 400
    assert "Zu diesem Auftrag gibt es inzwischen einen anderen Beleg: Entwurf" in r.text


def test_wettlauf_auf_dem_index_wird_zur_meldung_nicht_zu_500(pg_session, monkeypatch):
    """Zwei gleichzeitige Annahmen sehen beide 'frei' (Festlegung 19): Die
    Vorabpruefung liegt, der Index schlaegt beim Commit zu. Der Befund ist
    dann derselbe wie oben, kein HTTP 500. Die erste Frage der Route wird
    hier zur Luege gemacht, die zweite (im Fehlerweg) antwortet echt."""
    inv = _verworfen(pg_session)
    anderer = _beleg(pg_session, SCHLUESSEL, status="issued",
                     invoice_number="RE-4A-RENN")

    echt = auftragsschluessel.dokument_zu
    fragen = []

    def luegt_bei_der_ersten_frage(db, schluessel):
        fragen.append(schluessel)
        if len(fragen) == 1:
            return None
        return echt(db, schluessel)

    monkeypatch.setattr(auftragsschluessel, "dokument_zu",
                        luegt_bei_der_ersten_frage)

    r = _client(pg_session).post(f"/invoices/{inv.id}/zurueckholen")

    assert len(fragen) == 2
    assert r.status_code == 400
    assert ("Zu diesem Auftrag gibt es inzwischen einen anderen Beleg: "
            f"{anderer.invoice_number}") in r.text
    assert _frisch(pg_session, inv).status == "discarded"


# ── Finalisieren der Stornorechnung gibt das Original frei ───────────────────

@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
def test_finalisieren_der_stornorechnung_gibt_das_original_frei(pg_session):
    """Nicht das Anlegen des Storno-Entwurfs hebt das Original auf — erst die
    GESTELLTE Gutschrift (Festlegung 12). Solange der Entwurf nur besteht,
    sperrt das Original weiter; ein im Hintergrund eintreffender neuer Auftrag
    zum selben Schluessel wuerde zu Recht abgelehnt."""
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Muster Kunde GmbH",
                 address_line1="Kundenweg 1", zip_code="10115", city="Berlin",
                 country="DE")
    pg_session.add(c)
    pg_session.flush()
    original = orm_invoice_aus_auftrag(
        [InvoiceItem(position=1, description="Beratungsleistung", unit="Stunde",
                      quantity=Decimal("2"), unit_price=Decimal("100.00"),
                      tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                      tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))],
        SCHLUESSEL,
        customer=c,
        issue_date=date(2026, 7, 8), delivery_date=date(2026, 7, 8),
        due_date=date(2026, 7, 22), payment_terms="Zahlbar in 14 Tagen.",
        net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"), document_language="de",
    )
    pg_session.add(original)
    pg_session.commit()
    client = _client(pg_session)

    # Original stellen: es sperrt weiter (ein gestellter Beleg ist keiner,
    # der aufgehoeben waere).
    assert client.post(f"/invoices/{original.id}/finalisieren").status_code == 303
    original = _frisch(pg_session, original)
    assert original.status == "issued"
    assert original.auftragsschluessel_offen == SCHLUESSEL

    # Storno-Entwurf anlegen: das Original sperrt WEITER (nicht schon hier).
    assert client.post(f"/invoices/{original.id}/storno").status_code == 303
    original = _frisch(pg_session, original)
    storno = (pg_session.query(Invoice)
              .filter(Invoice.original_invoice_id == original.id).one())
    assert storno.invoice_type == "credit_note"
    assert original.auftragsschluessel_offen == SCHLUESSEL

    # Gutschrift stellen: das Original gibt den Schluessel frei, behaelt ihn
    # als Nachweis und behaelt seinen Status — genau warum der Status kein
    # Kriterium sein kann.
    assert client.post(f"/invoices/{storno.id}/finalisieren").status_code == 303
    original = _frisch(pg_session, original)
    assert original.status == "issued"
    assert original.auftragsschluessel == SCHLUESSEL
    assert original.auftragsschluessel_offen is None
    assert auftragsschluessel.dokument_zu(pg_session, SCHLUESSEL) is None
