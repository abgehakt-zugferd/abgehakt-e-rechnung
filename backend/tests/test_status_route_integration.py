"""
POST /invoices/{id}/status als ECHTE Integration (Audit-#10).

test_status_machine.py stellt die Statusübergänge nur an einem MagicMock-Invoice
fest: `assert inv.status == "paid"` beweist bloß, dass Python ein Attribut am Mock
setzt — NICHT, dass db.commit() feuert und die Änderung persistiert. Nachgewiesen
per Break-and-Revert: entfernt man db.commit() aus update_status, bleibt die
Mock-Suite grün.

Diese Tests re-queryen nach expire_all() die DB und haben damit Zähne: der fehlende
Commit würde hier auffallen. Zugleich läuft der invoice_guard real mit.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice


def teardown_function():
    app.dependency_overrides.clear()


def _invoice(pg_session, status):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("0"), tax_total=Decimal("0"), gross_total=Decimal("0"),
                  status=status)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    from fastapi.testclient import TestClient
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _db_status(pg_session, inv_id):
    pg_session.expire_all()
    return pg_session.get(Invoice, inv_id).status


@pytest.mark.parametrize("target", ["paid", "cancelled"])
def test_issued_transition_persists(pg_session, target):
    inv = _invoice(pg_session, "issued")
    r = _client(pg_session).post(f"/invoices/{inv.id}/status", data={"new_status": target})
    assert r.status_code == 303
    assert _db_status(pg_session, inv.id) == target   # persistiert (fängt fehlenden Commit)


@pytest.mark.parametrize("start,target", [
    ("cancelled", "paid"),
    ("draft", "cancelled"),
    ("paid", "cancelled"),
    ("draft", "paid"),
])
def test_illegal_transition_rejected_and_unchanged(pg_session, start, target):
    inv = _invoice(pg_session, start)
    r = _client(pg_session).post(f"/invoices/{inv.id}/status", data={"new_status": target})
    assert r.status_code == 400
    assert _db_status(pg_session, inv.id) == start    # DB unverändert


def test_unknown_target_status_rejected(pg_session):
    inv = _invoice(pg_session, "issued")
    r = _client(pg_session).post(f"/invoices/{inv.id}/status", data={"new_status": "banane"})
    assert r.status_code == 400
    assert _db_status(pg_session, inv.id) == "issued"
