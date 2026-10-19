"""Uebernahme der Kundenvorgaben in den Rechnungsentwurf (Bauschritt 2a, Festlegung 15).

Die Vorgaben werden KOPIERT, nicht gelesen: kopftext/fusstext (Platzhalter ersetzt)
stehen als eigene Spalten an der Rechnung, der Zahlungshinweis in payment_terms, die
Belegsprache aus der Vorgabe. Eine spaetere Aenderung am Kunden darf keinen
bestehenden Beleg erreichen — genau dafuer ist das Kopieren da.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services import kundenvorgaben
from app.services.audit import register_audit_listeners
from app.services.invoice_guard import InvoiceStateError, register_invoice_guard

# Reihenfolge wie in main.py: Guards zuerst, dann Audit.
register_invoice_guard()
register_audit_listeners()


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde(pg_session, **over):
    kw = dict(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Plattform GmbH",
              address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
              vat_id="DE123456789")
    kw.update(over)
    c = Customer(**kw)
    pg_session.add(c)
    pg_session.commit()
    return c


_ITEMS = [{"description": "Plattformumsaetze", "unit": "Stück",
           "quantity": "1", "unit_price": "100", "tax_rate": "19"}]


# ------------------------------------------------------------- Dienst (reine Form)

def _stamm_kunde(**over):
    kw = dict(customer_number="K-1", name="Plattform GmbH", address_line1="Weg 1",
              zip_code="10115", city="Berlin", country="DE")
    kw.update(over)
    return Customer(**kw)


def test_platzhalter_wird_zu_monat_jahr_des_zeitraums():
    kunde = _stamm_kunde(kopftext="Abrechnung {leistungsmonat}",
                         fusstext="Bericht {leistungsmonat}")
    v = kundenvorgaben.entwurfs_vorbelegung(kunde, date(2026, 9, 1), date(2026, 9, 30))
    assert v.kopftext == "Abrechnung 09/2026"
    assert v.fusstext == "Bericht 09/2026"


def test_ohne_zeitraum_wird_platzhalter_leer_ersetzt():
    """Ohne Zeitraum bleibt kein Roh-Platzhalter stehen; nichts wird beanstandet."""
    kunde = _stamm_kunde(kopftext="Abrechnung {leistungsmonat}")
    v = kundenvorgaben.entwurfs_vorbelegung(kunde, None, None)
    assert v.kopftext == "Abrechnung "
    assert "{leistungsmonat}" not in (v.kopftext or "")


def test_zahlungshinweis_und_belegsprache_nur_wenn_gesetzt():
    kunde = _stamm_kunde()
    v = kundenvorgaben.entwurfs_vorbelegung(kunde, date(2026, 9, 1), date(2026, 9, 30))
    assert v.zahlungshinweis is None
    assert v.belegsprache is None
    assert v.kopftext is None
    assert v.fusstext is None

    kunde = _stamm_kunde(zahlungshinweis="Zahlung nach Bericht.",
                         belegsprache_vorgabe="en")
    v = kundenvorgaben.entwurfs_vorbelegung(kunde, None, None)
    assert v.zahlungshinweis == "Zahlung nach Bericht."
    assert v.belegsprache == "en"


def test_ohne_kunden_gibt_es_keine_vorbelegung():
    v = kundenvorgaben.entwurfs_vorbelegung(None, date(2026, 9, 1), date(2026, 9, 30))
    assert v.kopftext is None
    assert v.fusstext is None
    assert v.zahlungshinweis is None
    assert v.belegsprache is None


# ------------------------------------------------- Anlegen einer Rechnung (Router)

def _anlegen(client, kunde_id, **over):
    daten = dict({
        "issue_date": "2026-10-05",
        "due_date": "2026-10-19",
        "service_period_start": "2026-09-01",
        "service_period_end": "2026-09-30",
        "tax_category": "S",
        "items_json": json.dumps(_ITEMS),
    })
    if kunde_id is not None:
        daten["customer_id"] = str(kunde_id)
    daten.update(over)
    return client.post("/invoices/neu", data=daten)


def test_neue_rechnung_bekommt_die_vorgaben(pg_session):
    kunde = _kunde(pg_session,
                   kopftext="Abrechnung {leistungsmonat}",
                   fusstext="Bericht ist Einzelaufstellung",
                   zahlungshinweis="Zahlung nach Auszahlungsbericht.",
                   belegsprache_vorgabe="en")
    r = _anlegen(_client(pg_session), kunde.id)
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()
    assert inv.kopftext == "Abrechnung 09/2026"
    assert inv.fusstext == "Bericht ist Einzelaufstellung"
    assert inv.payment_terms == "Zahlung nach Auszahlungsbericht."
    assert inv.document_language == "en"


def test_eingetippte_werte_gewinnen_ueber_die_vorgabe(pg_session):
    kunde = _kunde(pg_session, kopftext="Kunden-Kopf", fusstext="Kunden-Fuss",
                   zahlungshinweis="Kunden-Hinweis", belegsprache_vorgabe="en")
    r = _anlegen(_client(pg_session), kunde.id,
                 kopftext="Eigener Kopf", fusstext="Eigener Fuss",
                 payment_terms="Eigene Bedingungen", document_language="de")
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()
    assert inv.kopftext == "Eigener Kopf"
    assert inv.fusstext == "Eigener Fuss"
    assert inv.payment_terms == "Eigene Bedingungen"
    # Die Belegsprachenvorgabe gewinnt trotzdem: das Select schickt IMMER einen
    # Wert (Voreinstellung de), der Server kann Wahl und Nicht-Wahl nicht
    # unterscheiden. Aenderbar bleibt es im Entwurf.
    assert inv.document_language == "en"


def test_ohne_kunde_keine_vorbelegung(pg_session):
    r = _anlegen(_client(pg_session), None)
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id.is_(None)).one()
    assert inv.kopftext is None
    assert inv.fusstext is None
    assert inv.payment_terms == "Zahlbar innerhalb von 14 Tagen ohne Abzug."


def test_erstes_speichern_mit_kunde_fuellt_nur_leere_felder(pg_session):
    """Der Entwurf entstand ohne Kunde; die Vorbelegung greift erst, wenn beim
    ersten Speichern MIT Kunde noch nichts steht."""
    kunde = _kunde(pg_session, kopftext="Abrechnung {leistungsmonat}",
                   fusstext="Bericht ist Einzelaufstellung")
    client = _client(pg_session)
    r = _anlegen(client, None)
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id.is_(None)).one()

    r = client.post(f"/invoices/{inv.id}/bearbeiten", data={
        "customer_id": str(kunde.id),
        "issue_date": "2026-10-05",
        "due_date": "2026-10-19",
        "service_period_start": "2026-09-01",
        "service_period_end": "2026-09-30",
        "tax_category": "S",
        "items_json": json.dumps(_ITEMS),
        "kopftext": "",
        "fusstext": "",
    })
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.id == inv.id).one()
    assert inv.customer_id == kunde.id
    assert inv.kopftext == "Abrechnung 09/2026"
    assert inv.fusstext == "Bericht ist Einzelaufstellung"


def test_bearbeiten_speichert_kopf_und_fusstext_des_entwurfs(pg_session):
    kunde = _kunde(pg_session)
    client = _client(pg_session)
    r = _anlegen(client, kunde.id)
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()
    r = client.post(f"/invoices/{inv.id}/bearbeiten", data={
        "customer_id": str(kunde.id),
        "issue_date": "2026-10-05",
        "due_date": "2026-10-19",
        "service_period_start": "2026-09-01",
        "service_period_end": "2026-09-30",
        "tax_category": "S",
        "items_json": json.dumps(_ITEMS),
        "kopftext": "Neuer Kopf",
        "fusstext": "Neuer Fuss",
    })
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.id == inv.id).one()
    assert inv.kopftext == "Neuer Kopf"
    assert inv.fusstext == "Neuer Fuss"


# ------------------------------- Kopieren statt lesen: Bestand bleibt unberuehrt

def test_spaetere_kundenaenderung_aendert_keinen_bestehenden_beleg(pg_session):
    kunde = _kunde(pg_session, kopftext="Abrechnung {leistungsmonat}",
                   fusstext="Bericht ist Einzelaufstellung",
                   zahlungshinweis="Zahlung nach Bericht.",
                   belegsprache_vorgabe="en")
    client = _client(pg_session)
    assert _anlegen(client, kunde.id).status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()
    assert inv.kopftext == "Abrechnung 09/2026"

    r = client.post(f"/customers/{kunde.id}/bearbeiten", data={
        "name": "Plattform GmbH", "address_line1": "Weg 1",
        "zip_code": "10115", "city": "Berlin",
        "customer_number": kunde.customer_number,
        "kopftext": "Gaenzlich andere Grundlage",
        "fusstext": "Gaenzlich anderer Fuss",
        "zahlungshinweis": "Gaenzlich anderer Hinweis",
        "belegsprache_vorgabe": "de",
    })
    assert r.status_code == 303

    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.id == inv.id).one()
    assert inv.kopftext == "Abrechnung 09/2026"
    assert inv.fusstext == "Bericht ist Einzelaufstellung"
    assert inv.payment_terms == "Zahlung nach Bericht."
    assert inv.document_language == "en"


# ----------------------------------------- Guard: nach Finalisieren Rechnungsinhalt

def _rechnung(pg_session, status="issued", kunde=None, **kw):
    if kunde is None:
        kunde = _kunde(pg_session)
    inv = Invoice(
        invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 6, 11), due_date=date(2026, 6, 25),
        currency="EUR", zugferd_profile="EN16931", tax_category="S",
        net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"), status=status, **kw,
    )
    pg_session.add(inv)
    pg_session.commit()
    return inv


@pytest.mark.parametrize("feld", ["kopftext", "fusstext"])
def test_guard_schuetzt_kopf_und_fusstext_nach_finalisieren(pg_session, feld):
    inv = _rechnung(pg_session, status="issued", kopftext="Kopf", fusstext="Fuss")
    setattr(inv, feld, "nachtraeglich geaendert")
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


@pytest.mark.parametrize("feld", ["kopftext", "fusstext"])
def test_entwurf_bleibt_bearbeitbar(pg_session, feld):
    inv = _rechnung(pg_session, status="draft")
    setattr(inv, feld, "im Entwurf geaendert")
    pg_session.commit()
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.id == inv.id).one()
    assert getattr(inv, feld) == "im Entwurf geaendert"
