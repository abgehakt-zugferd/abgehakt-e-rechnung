"""Ersatzrechnung: Regeln am Anlageweg und beim Finalisieren (docs/specs/ersatzrechnung.md).

Naht ist POST /invoices/neu mit `ersetzt_invoice_id`. Eine Ablehnung muss vor der
Nummernvergabe fallen: kein Datensatz, kein erhoehter Zaehler.
Die Pipeline bis zum ZUGFeRD-PDF prueft test_ersatzrechnung_e2e.py.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.invoice import Invoice
from tests.helpers.ersatzrechnung import (
    kunde as _kunde,
    beleg as _beleg,
    gutschrift as _gutschrift,
    payload as _payload,
    zaehler as _zaehler,
    stornierte as _stornierte,
    ersatz_entwurf as _ersatz_entwurf,
    ersatz_ueber_formular as _ersatz_ueber_formular,
)


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _abgelehnt_ohne_wirkung(pg_session, client, payload, code):
    zaehler_vorher = _zaehler(pg_session)
    anzahl_vorher = pg_session.query(Invoice).count()

    r = client.post("/invoices/neu", data=payload)

    assert r.status_code == 400, r.text
    assert code in r.text
    pg_session.expire_all()
    assert pg_session.query(Invoice).count() == anzahl_vorher
    assert _zaehler(pg_session) == zaehler_vorher, (
        "Abgelehnte Ersatzrechnung hat den Nummernzaehler erhoeht (Nummernluecke ohne Beleg)."
    )


def test_ersatz_ohne_gutschrift_wird_vor_der_nummernvergabe_abgelehnt(pg_session, client):
    kunde = _kunde(pg_session)
    original = _beleg(pg_session, kunde)

    _abgelehnt_ohne_wirkung(pg_session, client, _payload(kunde, original.id),
                            "ERSATZ_OHNE_GUTSCHRIFT")


@pytest.mark.parametrize("kennung", ["kaputt", str(uuid.uuid4())])
def test_ersatz_zu_unbekannter_rechnung_wird_abgelehnt(pg_session, client, kennung):
    kunde = _kunde(pg_session)

    _abgelehnt_ohne_wirkung(pg_session, client, _payload(kunde, kennung),
                            "ERSATZ_ORIGINAL_UNBEKANNT")


@pytest.mark.parametrize("lage", ["gutschrift", "honorargutschrift", "entwurf", "verworfen"])
def test_nur_eine_gestellte_rechnung_ist_ersetzbar(pg_session, client, lage):
    kunde = _kunde(pg_session)
    if lage == "gutschrift":
        quelle = _gutschrift(pg_session, _beleg(pg_session, kunde))
    elif lage == "honorargutschrift":
        quelle = _beleg(pg_session, kunde, invoice_type="self_billing",
                        original=_beleg(pg_session, kunde))
    else:
        quelle = _beleg(pg_session, kunde,
                        status="draft" if lage == "entwurf" else "discarded")
    # Eine Gutschrift auf die Quelle, damit nicht die Gutschrift-Regel antwortet.
    _gutschrift(pg_session, quelle)

    _abgelehnt_ohne_wirkung(pg_session, client, _payload(kunde, quelle.id),
                            "ERSATZ_ORIGINAL_KEINE_RECHNUNG")


def test_zweite_ersatzrechnung_zum_selben_original_wird_abgelehnt(pg_session, client):
    kunde = _kunde(pg_session)
    original = _stornierte(pg_session, kunde)
    assert client.post("/invoices/neu", data=_payload(kunde, original.id)).status_code == 303

    _abgelehnt_ohne_wirkung(pg_session, client, _payload(kunde, original.id),
                            "ERSATZ_SCHON_VORHANDEN")


def test_verworfener_ersatz_zaehlt_nicht(pg_session, client):
    kunde = _kunde(pg_session)
    original = _stornierte(pg_session, kunde)
    assert client.post("/invoices/neu", data=_payload(kunde, original.id)).status_code == 303
    pg_session.expire_all()
    erster = pg_session.query(Invoice).filter(Invoice.ersetzt_invoice_id == original.id).one()
    assert client.post(f"/invoices/{erster.id}/verwerfen").status_code == 303

    r = client.post("/invoices/neu", data=_payload(kunde, original.id))

    assert r.status_code == 303, r.text


def test_datenbank_haelt_hoechstens_einen_aktiven_ersatz_pro_original(pg_session):
    """Zweite Schicht unter der Vorabpruefung: zwei ueberlappende Anfragen."""
    from sqlalchemy.exc import IntegrityError

    kunde = _kunde(pg_session)
    original = _stornierte(pg_session, kunde)
    _ersatz_entwurf(pg_session, kunde, original, status="discarded")
    _ersatz_entwurf(pg_session, kunde, original)
    pg_session.commit()

    _ersatz_entwurf(pg_session, kunde, original)
    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()


def test_ersatz_ist_erst_nach_gestellter_gutschrift_finalisierbar(pg_session, client):
    kunde = _kunde(pg_session)
    original = _beleg(pg_session, kunde)
    _gutschrift(pg_session, original, status="draft")
    ersatz = _ersatz_ueber_formular(pg_session, client, kunde, original)

    r = client.post(f"/invoices/{ersatz.id}/finalisieren")

    assert r.status_code == 400, r.text
    # Das Finalisieren zeigt Meldungstexte, nicht Codes.
    assert f"Gutschrift zu Rechnung {original.invoice_number} ist noch nicht gestellt" in r.text
    pg_session.expire_all()
    row = pg_session.get(Invoice, ersatz.id)
    assert row.status == "draft"
    assert row.zugferd_xml is None


def test_ein_beleg_traegt_nie_beide_bezuege(pg_session):
    """`_reference_xml` schreibt nur einen BT-25; der zweite Bezug ginge still verloren."""
    from app.services.validator import validate_invoice

    kunde = _kunde(pg_session)
    original = _beleg(pg_session, kunde)
    andere = _stornierte(pg_session, kunde)
    gutschrift = _beleg(pg_session, kunde, status="draft", invoice_type="credit_note",
                        original=original)
    gutschrift.ersetzt_invoice_id = andere.id
    pg_session.commit()

    fehler, _ = validate_invoice(gutschrift, pg_session.get(Company, 1))

    assert "ERSATZ_DOPPELTER_BEZUG" in [f.code for f in fehler]


def test_gutschrift_mit_ersatz_laesst_sich_nicht_stornieren(pg_session, client):
    """Sonst lebte das Original neben seinem Ersatz wieder auf."""
    kunde = _kunde(pg_session)
    original = _beleg(pg_session, kunde)
    gutschrift = _gutschrift(pg_session, original)
    _ersatz_ueber_formular(pg_session, client, kunde, original)

    r = client.post(f"/invoices/{gutschrift.id}/status", data={"new_status": "cancelled"})

    assert r.status_code == 400, r.text
    assert "ERSATZ_GUTSCHRIFT_GEBUNDEN" in r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, gutschrift.id).status == "issued"


def test_gutschrift_ohne_ersatz_bleibt_stornierbar(pg_session, client):
    kunde = _kunde(pg_session)
    gutschrift = _gutschrift(pg_session, _beleg(pg_session, kunde))

    r = client.post(f"/invoices/{gutschrift.id}/status", data={"new_status": "cancelled"})

    assert r.status_code == 303, r.text


def test_zurueckholen_eines_ersatzes_prueft_den_bezug_erneut(pg_session, client):
    kunde = _kunde(pg_session)
    original = _stornierte(pg_session, kunde)
    erster = _ersatz_ueber_formular(pg_session, client, kunde, original)
    assert client.post(f"/invoices/{erster.id}/verwerfen").status_code == 303
    _ersatz_ueber_formular(pg_session, client, kunde, original)

    r = client.post(f"/invoices/{erster.id}/zurueckholen")

    assert r.status_code == 400, r.text
    assert "ERSATZ_SCHON_VORHANDEN" in r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, erster.id).status == "discarded"


def test_zurueckholen_ohne_konkurrenz_geht(pg_session, client):
    kunde = _kunde(pg_session)
    original = _stornierte(pg_session, kunde)
    erster = _ersatz_ueber_formular(pg_session, client, kunde, original)
    assert client.post(f"/invoices/{erster.id}/verwerfen").status_code == 303

    assert client.post(f"/invoices/{erster.id}/zurueckholen").status_code == 303


def test_bearbeiten_behaelt_den_bezug_und_lehnt_einen_neuen_ab(pg_session, client):
    kunde = _kunde(pg_session)
    original = _stornierte(pg_session, kunde)
    andere = _stornierte(pg_session, kunde)
    ersatz = _ersatz_ueber_formular(pg_session, client, kunde, original)
    daten = _payload(kunde, None)
    del daten["ersetzt_invoice_id"]

    assert client.post(f"/invoices/{ersatz.id}/bearbeiten", data=daten).status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Invoice, ersatz.id).ersetzt_invoice_id == original.id

    daten["ersetzt_invoice_id"] = str(andere.id)
    r = client.post(f"/invoices/{ersatz.id}/bearbeiten", data=daten)
    assert r.status_code == 400, r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, ersatz.id).ersetzt_invoice_id == original.id
