"""Tests fuer Migration: Versand/Bezahlt aus altem System nachziehen."""

from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceSendLog
from scripts.beleg_migration_nachziehen import nachziehen


def _inv(pg_session, number, issue, due):
    c = Customer(
        customer_number=f"K-MIG-{number}",
        name="Migration Kunde",
        email="kunde@example.de",
        address_line1="Weg 1",
        zip_code="80331",
        city="München",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(
        invoice_number=number,
        customer_id=c.id,
        issue_date=issue,
        due_date=due,
        currency="EUR",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        status="issued",
        pdf_filename=f"{number}.pdf",
    )
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_nachziehen_setzt_versand_und_bezahlt(pg_session):
    inv = _inv(pg_session, "MIG-001", date(2026, 7, 8), date(2026, 7, 22))
    nachziehen(["MIG-001"], db=pg_session)

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.invoice_number == "MIG-001").one()
    assert row.status == "paid"
    assert row.datev_sent_at == datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    assert row.updated_at == datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    log = pg_session.query(InvoiceSendLog).filter(InvoiceSendLog.invoice_id == row.id).one()
    assert log.success is True
    assert "vorheriges Abgehakt" in log.error
