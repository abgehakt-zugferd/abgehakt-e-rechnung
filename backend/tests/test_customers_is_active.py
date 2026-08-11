"""
Customer.is_active (#98 P2): die Spalte + der Filter (new_invoice_form:
Customer.is_active == True) existierten, aber es gab keine UI, sie zu setzen —
ein „halber Zustand". Hier wird der Status über das Kunden-Formular setzbar und der
Effekt (inaktive Kunden erscheinen NICHT in der Rechnungs-Kundenauswahl) bewiesen.
"""
import uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


_REQUIRED = {"name": "Muster GmbH", "address_line1": "Weg 1", "zip_code": "10115", "city": "Berlin"}


def _seed(pg_session, **over):
    kw = dict(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Alt", address_line1="Alt 1",
              zip_code="10115", city="Berlin", country="DE")
    kw.update(over)
    c = Customer(**kw)
    pg_session.add(c)
    pg_session.commit()
    return c


def test_create_defaults_active(pg_session):
    r = _client(pg_session).post("/customers/neu",
                                 data={**_REQUIRED, "customer_number": "20260701"})
    assert r.status_code == 303
    pg_session.expire_all()
    c = pg_session.query(Customer).filter(Customer.customer_number == "20260701").first()
    assert c.is_active is True


def test_create_inactive(pg_session):
    r = _client(pg_session).post("/customers/neu",
                                 data={**_REQUIRED, "customer_number": "20260702", "is_active": "0"})
    assert r.status_code == 303
    pg_session.expire_all()
    c = pg_session.query(Customer).filter(Customer.customer_number == "20260702").first()
    assert c.is_active is False


def test_update_can_deactivate_and_reactivate(pg_session):
    c = _seed(pg_session, customer_number="20260703")
    _client(pg_session).post(f"/customers/{c.id}/bearbeiten",
                             data={**_REQUIRED, "customer_number": "20260703", "is_active": "0"})
    pg_session.expire_all()
    assert pg_session.get(Customer, c.id).is_active is False

    _client(pg_session).post(f"/customers/{c.id}/bearbeiten",
                             data={**_REQUIRED, "customer_number": "20260703", "is_active": "1"})
    pg_session.expire_all()
    assert pg_session.get(Customer, c.id).is_active is True


def test_inactive_customer_hidden_from_new_invoice_dropdown(pg_session):
    active = _seed(pg_session, customer_number="20260704", name="Aktiv GmbH", is_active=True)
    inactive = _seed(pg_session, customer_number="20260705", name="Inaktiv GmbH", is_active=False)
    r = _client(pg_session).get("/invoices/neu")
    assert r.status_code == 200
    assert "Aktiv GmbH" in r.text
    assert "Inaktiv GmbH" not in r.text
