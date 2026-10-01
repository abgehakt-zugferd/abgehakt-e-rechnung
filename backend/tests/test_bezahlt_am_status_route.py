"""POST /invoices/{id}/status setzt bezahlt_am beim Uebergang nach paid."""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.zeit import heute


def teardown_function():
    app.dependency_overrides.clear()


def _issued(pg_session, issue: date | None = None) -> Invoice:
    issue = issue or date(2026, 6, 1)
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Status GmbH",
        address_line1="Probeweg 2",
        zip_code="80331",
        city="Muenchen",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:6]}",
        customer_id=c.id,
        issue_date=issue,
        due_date=issue,
        currency="EUR",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        status="issued",
    )
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def test_status_paid_setzt_bezahlt_am_aus_formular(pg_session):
    inv = _issued(pg_session, issue=date(2026, 6, 1))
    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status",
        data={"new_status": "paid", "bezahlt_am": "2026-06-10"},
    )
    assert r.status_code == 303
    pg_session.expire_all()
    row = pg_session.get(Invoice, inv.id)
    assert row.status == "paid"
    assert row.bezahlt_am == date(2026, 6, 10)


def test_status_paid_ohne_datum_nimmt_heute(pg_session):
    inv = _issued(pg_session)
    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status",
        data={"new_status": "paid"},
    )
    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).bezahlt_am == heute()


def test_status_paid_lehnt_zukunft_ab(pg_session):
    inv = _issued(pg_session)
    zukunft = (heute() + timedelta(days=2)).isoformat()
    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status",
        data={"new_status": "paid", "bezahlt_am": zukunft},
    )
    assert r.status_code == 400
    assert "Zukunft" in r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "issued"


def test_status_paid_lehnt_datum_vor_rechnung_ab(pg_session):
    inv = _issued(pg_session, issue=date(2026, 6, 10))
    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status",
        data={"new_status": "paid", "bezahlt_am": "2026-06-01"},
    )
    assert r.status_code == 400
    assert "Rechnungsdatum" in r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "issued"


def test_status_paid_lehnt_unlesbares_datum_ab(pg_session):
    inv = _issued(pg_session)
    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status",
        data={"new_status": "paid", "bezahlt_am": "10.06.2026"},
    )
    assert r.status_code == 400
    assert "Datum" in r.text or "datum" in r.text.lower()
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "issued"
