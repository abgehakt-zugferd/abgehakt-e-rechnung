"""Eine gestellte Gutschrift ist endgueltig (Issue #142).

Entscheidung des Betreibers vom 08.10.2026: Gutschriften lassen sich nicht stornieren.
Die Gutschrift ist selbst die Korrektur; war sie falsch, wird zum Original eine neue
Rechnung gestellt (Ersatzrechnung, docs/specs/ersatzrechnung.md). Das Programm sperrt
nicht nur, es zeigt den Weg.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.invoice import Invoice
from tests.helpers.ersatzrechnung import beleg, gutschrift, kunde


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def test_gestellte_gutschrift_laesst_sich_nicht_stornieren_und_zeigt_den_weg(pg_session, client):
    original = beleg(pg_session, kunde(pg_session))
    gs = gutschrift(pg_session, original)

    r = client.post(f"/invoices/{gs.id}/status", data={"new_status": "cancelled"})

    assert r.status_code == 400, r.text
    assert "GUTSCHRIFT_NICHT_STORNIERBAR" in r.text
    assert "Ersatzrechnung" in r.text
    assert original.invoice_number in r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, gs.id).status == "issued"
