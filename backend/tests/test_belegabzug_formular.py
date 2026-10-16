"""Abzug in Formular, Detailansicht und Vorbelegung (Issue #147, Teil B1).

Kopieren uebernimmt den Abzug nicht: er ist typischerweise eine einmalige
Anrechnung, eine Kopie wuerde ihn still verdoppeln. Die Ersatzrechnung
uebernimmt ihn, weil sie dieselbe Rechnung ersetzt. Bearbeiten und Detailseite
zeigen das gespeicherte Paar.
"""
import json
import re
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.invoice import Invoice, InvoiceItem
from tests.helpers.ersatzrechnung import gutschrift, kunde

GRUND = "Anrechnung Vorleistung"
BETRAG = Decimal("100.00")


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _feldwert(html: str, name: str):
    """value-Attribut des Eingabefelds; fehlt das Attribut, None."""
    m = re.search(rf'<input[^>]*name="{re.escape(name)}"[^>]*>', html)
    assert m, f"Eingabefeld {name} fehlt"
    wert = re.search(r'value="([^"]*)"', m.group(0))
    return wert.group(1) if wert else None


def _rechnung_mit_abzug(pg_session, kunde, betrag=BETRAG):
    """Gestellte Rechnung mit Abzug, Abzug von Anfang an (invoice_guard:
    nachtraegliches Setzen waere ein Eingriff in einen finalisierten Beleg)."""
    # Positionssumme 1000,00: net_total ist die Basis NACH Abzug (#147).
    netto = Decimal("1000.00") - betrag
    steuer = (netto * Decimal("19") / 100).quantize(Decimal("0.01"))
    inv = Invoice(invoice_number=f"RE-ABZ-{uuid.uuid4().hex[:6]}",
                  customer_id=kunde.id,
                  issue_date=date(2026, 10, 1), due_date=date(2026, 10, 15),
                  delivery_date=date(2026, 10, 1), currency="EUR",
                  tax_category="S", status="issued",
                  net_total=netto, tax_total=steuer, gross_total=netto + steuer,
                  abzug_betrag=betrag, abzug_grund=GRUND)
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Stunde",
                             quantity=Decimal("10"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("1000.00"),
                             tax_amount=Decimal("190.00"), gross_amount=Decimal("1190.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _stammdaten(kunde):
    return {
        "customer_id": str(kunde.id),
        "issue_date": "2026-10-01",
        "due_date": "2026-10-15",
        "tax_category": "S",
    }


def _positionen_netto_1000():
    # 10 Stunden zu 100,00 netto, 19 Prozent: Positionssumme 1000,00.
    return json.dumps([{"description": "Beratung", "unit": "Stunde",
                        "quantity": "10", "unit_price": "100", "tax_rate": "19"}])


def _entwurf_mit_abzug(pg_session, client, kunde):
    """Entwurf ueber den echten POST anlegen: Positionssumme 1000, Abzug 100."""
    r = client.post("/invoices/neu", data={
        **_stammdaten(kunde),
        "items_json": _positionen_netto_1000(),
        "abzug_betrag": "100,00",
        "abzug_grund": GRUND,
    })
    assert r.status_code == 303, r.text
    return r.headers["location"].rsplit("/", 1)[-1]


def test_kopieren_belegt_den_abzug_nicht_vor(pg_session, client):
    vorlage = _rechnung_mit_abzug(pg_session, kunde(pg_session))

    r = client.get(f"/invoices/neu?vorlage={vorlage.id}")

    assert r.status_code == 200, r.text
    assert _feldwert(r.text, "abzug_betrag") == ""
    assert _feldwert(r.text, "abzug_grund") == ""
    assert GRUND not in r.text, "Abzugsgrund der Vorlage darf nicht durchsickern"


def test_ersatzrechnung_belegt_betrag_und_grund_vor(pg_session, client):
    k = kunde(pg_session)
    original = _rechnung_mit_abzug(pg_session, k, Decimal("25.00"))
    gutschrift(pg_session, original)

    r = client.get(f"/invoices/neu?ersetzt={original.id}")

    assert r.status_code == 200, r.text
    assert _feldwert(r.text, "abzug_betrag") == "25.00"
    assert _feldwert(r.text, "abzug_grund") == GRUND


def test_bearbeiten_zeigt_gespeicherten_abzug(pg_session, client):
    inv_id = _entwurf_mit_abzug(pg_session, client, kunde(pg_session))

    r = client.get(f"/invoices/{inv_id}/bearbeiten")

    assert r.status_code == 200, r.text
    assert _feldwert(r.text, "abzug_betrag") == "100.00"
    assert _feldwert(r.text, "abzug_grund") == GRUND


def test_detailseite_mit_abzug_zeigt_positionssumme_und_grund(pg_session, client):
    inv_id = _entwurf_mit_abzug(pg_session, client, kunde(pg_session))

    text = client.get(f"/invoices/{inv_id}").text

    assert "Positionssumme" in text
    assert f"Abzug: {GRUND}" in text
    assert "1.000,00" in text  # Positionssumme vor Abzug
    assert "900,00" in text    # Netto nach Abzug


def test_detailseite_ohne_abzug_zeigt_keine_positionssumme(pg_session, client):
    k = kunde(pg_session)
    r = client.post("/invoices/neu", data={
        **_stammdaten(k),
        "items_json": _positionen_netto_1000(),
    })
    assert r.status_code == 303, r.text
    inv_id = r.headers["location"].rsplit("/", 1)[-1]

    text = client.get(f"/invoices/{inv_id}").text

    assert "Positionssumme" not in text
