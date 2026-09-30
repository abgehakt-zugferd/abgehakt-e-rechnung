"""invoice_guard: bezahlt_am nur mit issued→paid, danach forward-only."""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services.audit import register_audit_listeners
from app.services.invoice_guard import InvoiceStateError, register_invoice_guard

register_invoice_guard()
register_audit_listeners()


def _kunde(session) -> Customer:
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Guard GmbH",
        address_line1="Probeweg 3",
        zip_code="80331",
        city="Muenchen",
        country="DE",
    )
    session.add(c)
    session.flush()
    return c


def _inv(session, status="issued", **kw) -> Invoice:
    c = kw.pop("customer", None) or _kunde(session)
    inv = Invoice(
        invoice_number=kw.pop("invoice_number", f"RE-{uuid.uuid4().hex[:6]}"),
        customer_id=c.id,
        issue_date=kw.pop("issue_date", date(2026, 6, 11)),
        due_date=kw.pop("due_date", date(2026, 6, 25)),
        currency="EUR",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        status=status,
        **kw,
    )
    session.add(inv)
    session.commit()
    return inv


def test_bezahlt_am_mit_issued_nach_paid_erlaubt(pg_session):
    inv = _inv(pg_session, status="issued")
    inv.status = "paid"
    inv.bezahlt_am = date(2026, 6, 20)
    pg_session.commit()
    assert inv.bezahlt_am == date(2026, 6, 20)


def test_bezahlt_am_aendern_auf_paid_verboten(pg_session):
    inv = _inv(pg_session, status="paid", bezahlt_am=date(2026, 6, 20))
    inv.bezahlt_am = date(2026, 7, 1)
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_bezahlt_am_leeren_verboten(pg_session):
    inv = _inv(pg_session, status="paid", bezahlt_am=date(2026, 6, 20))
    inv.bezahlt_am = None
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_bezahlt_am_auf_issued_ohne_statuswechsel_verboten(pg_session):
    inv = _inv(pg_session, status="issued")
    inv.bezahlt_am = date(2026, 6, 20)
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()
