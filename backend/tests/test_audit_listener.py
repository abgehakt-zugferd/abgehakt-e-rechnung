"""
GoBD: Das Audit-Log muss automatisch und lückenlos befüllt werden — per
Session-Event, nicht per Handler-Disziplin. Integrationstests gegen echte DB.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.customer import Customer
from app.models.invoice import Invoice, AuditLog
from app.services.audit import register_audit_listeners

register_audit_listeners()  # idempotent — mehrfacher Aufruf darf nicht doppelt loggen


def _customer(number="K-1") -> Customer:
    return Customer(
        customer_number=number, name="Audit GmbH",
        address_line1="Weg 1", zip_code="12345", city="Musterstadt",
    )


def test_insert_customer_writes_audit_row(pg_session):
    c = _customer()
    pg_session.add(c)
    pg_session.commit()

    rows = pg_session.query(AuditLog).filter_by(table_name="customers").all()
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "insert"
    assert row.record_id == str(c.id)
    assert row.old_values is None
    assert row.new_values["name"] == "Audit GmbH"


def test_update_customer_logs_only_changed_columns(pg_session):
    c = _customer()
    pg_session.add(c)
    pg_session.commit()

    c.city = "Augsburg"
    pg_session.commit()

    rows = (
        pg_session.query(AuditLog)
        .filter_by(table_name="customers", action="update")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].old_values == {"city": "Musterstadt"}
    assert rows[0].new_values == {"city": "Augsburg"}


def test_double_registration_does_not_duplicate_rows(pg_session):
    register_audit_listeners()  # zweiter Aufruf
    c = _customer("K-2")
    pg_session.add(c)
    pg_session.commit()
    assert pg_session.query(AuditLog).filter_by(record_id=str(c.id)).count() == 1


def test_invoice_insert_is_audited_with_serialized_values(pg_session):
    c = _customer("K-3")
    pg_session.add(c)
    pg_session.commit()

    inv = Invoice(
        invoice_number="RE-2026-777", customer_id=c.id,
        issue_date=date(2026, 7, 8), due_date=date(2026, 7, 22),
        net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
    )
    pg_session.add(inv)
    pg_session.commit()

    row = pg_session.query(AuditLog).filter_by(table_name="invoices").one()
    assert row.action == "insert"
    assert row.new_values["gross_total"] == "119.00"      # Decimal → str
    assert row.new_values["issue_date"] == "2026-07-08"   # date → ISO
    assert row.new_values["customer_id"] == str(c.id)     # UUID → str


def test_audit_rows_themselves_are_not_audited(pg_session):
    c = _customer("K-4")
    pg_session.add(c)
    pg_session.commit()
    # Es existiert genau 1 Audit-Zeile (für den Kunden) — keine Zeile über audit_log selbst.
    assert pg_session.query(AuditLog).count() == 1
