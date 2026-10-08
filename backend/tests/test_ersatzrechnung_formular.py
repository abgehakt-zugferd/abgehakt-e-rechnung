"""Ersatzrechnung im Anlegeformular: GET /invoices/neu?ersetzt=<id> (docs/specs/ersatzrechnung.md).

Belegt vor wie das Kopieren (docs/specs/kopieren.md), traegt den Bezug als verstecktes
Feld und, anders als das Kopieren, die Belegart des Originals.
"""
import re

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from tests.helpers.ersatzrechnung import beleg, gutschrift, kunde


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _gewaehlt(html: str, name: str):
    m = re.search(rf'<select[^>]*name="{re.escape(name)}"[^>]*>(.*?)</select>', html, re.S)
    assert m, f"Auswahlfeld {name} fehlt"
    treffer = re.search(r'<option value="([^"]*)"[^>]*selected', m.group(1))
    return treffer.group(1) if treffer else None


def test_formular_belegt_ersatz_mit_bezug_und_belegart_vor(pg_session, client):
    k = kunde(pg_session)
    original = beleg(pg_session, k, invoice_type="prepayment")
    gutschrift(pg_session, original)

    r = client.get(f"/invoices/neu?ersetzt={original.id}")

    assert r.status_code == 200, r.text
    assert f'name="ersetzt_invoice_id" value="{original.id}"' in r.text
    assert f"Ersetzt Rechnung {original.invoice_number}" in r.text
    assert _gewaehlt(r.text, "invoice_type") == "prepayment"
    assert _gewaehlt(r.text, "customer_id") == str(k.id)
    assert "Beratung" in r.text


def test_formular_ohne_gutschrift_sagt_warum(pg_session, client):
    original = beleg(pg_session, kunde(pg_session))

    r = client.get(f"/invoices/neu?ersetzt={original.id}")

    assert r.status_code == 400
    assert "ERSATZ_OHNE_GUTSCHRIFT" in r.text
    assert 'name="ersetzt_invoice_id"' not in r.text


def test_kopie_einer_ersatzrechnung_erbt_den_bezug_nicht(pg_session, client):
    """Feldvertrag kopieren.md: der Bezug haengt die Kopie sonst an eine fremde Kette."""
    from tests.helpers.ersatzrechnung import ersatz_ueber_formular, stornierte

    k = kunde(pg_session)
    ersatz = ersatz_ueber_formular(pg_session, client, k, stornierte(pg_session, k))

    r = client.get(f"/invoices/neu?vorlage={ersatz.id}")

    assert r.status_code == 200, r.text
    assert 'name="ersetzt_invoice_id"' not in r.text
    assert "Ersetzt Rechnung" not in r.text
