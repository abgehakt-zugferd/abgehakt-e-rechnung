"""Kunden-UI: Schnittstellen-ID (UUID) fuer Abrechnungsauftrag — #66."""
import uuid

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from fastapi.testclient import TestClient


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _seed(pg_session, **over):
    kw = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Muster GmbH",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
    )
    kw.update(over)
    c = Customer(**kw)
    pg_session.add(c)
    pg_session.commit()
    return c


def test_kundenliste_zeigt_schnittstellen_id(pg_session):
    c = _seed(pg_session)
    r = _client(pg_session).get("/customers/")
    assert r.status_code == 200
    assert "SCHNITTSTELLEN-ID" in r.text
    assert str(c.id) in r.text
    assert "abgehaktKopieren" in r.text


def test_kundenformular_zeigt_schnittstellen_id(pg_session):
    c = _seed(pg_session)
    r = _client(pg_session).get(f"/customers/{c.id}/bearbeiten")
    assert r.status_code == 200
    assert "Schnittstellen-ID" in r.text
    assert str(c.id) in r.text
    assert "Tantiemen-App" in r.text
    assert f"id=\"schnittstellen-id-{c.id}\"" in r.text


def test_neues_kundenformular_ohne_schnittstellen_id(pg_session):
    r = _client(pg_session).get("/customers/neu")
    assert r.status_code == 200
    assert "Schnittstellen-ID" not in r.text
