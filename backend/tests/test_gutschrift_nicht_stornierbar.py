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


def test_waechter_sperrt_das_stornieren_einer_gutschrift_auf_jedem_weg(pg_session):
    """Zweite Schicht unter der Route: auch Skript oder Shell kommen nicht vorbei.
    `paid` ist im Waechter ohnehin Endzustand; offen war nur issued -> cancelled."""
    from app.services.invoice_guard import InvoiceStateError

    gs = gutschrift(pg_session, beleg(pg_session, kunde(pg_session)))

    gs.status = "cancelled"
    with pytest.raises(InvoiceStateError, match="Gutschrift"):
        pg_session.flush()
    pg_session.rollback()


def test_waechter_laesst_rechnungen_weiter_stornieren(pg_session):
    original = beleg(pg_session, kunde(pg_session))

    original.status = "cancelled"
    pg_session.commit()

    assert original.status == "cancelled"


def test_detailseite_einer_gutschrift_bietet_kein_stornieren_sondern_den_weg(pg_session, client):
    original = beleg(pg_session, kunde(pg_session))
    gs = gutschrift(pg_session, original)

    text = client.get(f"/invoices/{gs.id}").text

    assert 'name="new_status" value="cancelled"' not in text
    assert "endgültig" in text
    assert f'href="/invoices/neu?ersetzt={original.id}"' in text


def test_detailseite_einer_rechnung_bietet_das_stornieren_weiter_an(pg_session, client):
    rechnung = beleg(pg_session, kunde(pg_session))

    text = client.get(f"/invoices/{rechnung.id}").text

    assert 'name="new_status" value="cancelled"' in text
