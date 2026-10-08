"""Gemeinsame Bausteine der Ersatzrechnungstests (docs/specs/ersatzrechnung.md)."""
import json
import uuid
from datetime import date
from decimal import Decimal

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


def kunde(pg_session, name="Probe Kunde GmbH"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
                 address_line1="Weg 1", zip_code="80331", city="Muenchen", country="DE")
    pg_session.add(c)
    pg_session.flush()
    return c


def beleg(pg_session, kunde, *, status="issued", invoice_type=None, original=None):
    inv = Invoice(invoice_number=f"RE-ERS-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=date(2026, 7, 8), due_date=date(2026, 7, 22),
                  delivery_date=date(2026, 7, 8), currency="EUR", tax_category="S",
                  status=status, invoice_type=invoice_type,
                  original_invoice_id=original.id if original else None,
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"))
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Stunde",
                             quantity=Decimal("1"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                             tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def gutschrift(pg_session, original, *, status="issued"):
    return beleg(pg_session, original.customer, status=status,
                  invoice_type="credit_note", original=original)


def payload(kunde, ersetzt):
    return {
        "customer_id": str(kunde.id),
        "issue_date": "2026-07-10",
        "due_date": "2026-07-24",
        "tax_category": "S",
        "ersetzt_invoice_id": str(ersetzt) if ersetzt is not None else "",
        "items_json": json.dumps([{"description": "Beratung", "unit": "Stunde",
                                   "quantity": "1", "unit_price": "100",
                                   "tax_rate": "19"}]),
    }


def zaehler(pg_session):
    return pg_session.query(Company).filter(Company.id == 1).one().invoice_counter


def stornierte(pg_session, kunde):
    original = beleg(pg_session, kunde)
    gutschrift(pg_session, original)
    return original


def ersatz_entwurf(pg_session, kunde, original, *, status="draft"):
    inv = Invoice(invoice_number=f"RE-ERS-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=date(2026, 7, 10), due_date=date(2026, 7, 24),
                  currency="EUR", tax_category="S", status=status,
                  ersetzt_invoice_id=original.id)
    pg_session.add(inv)
    return inv


def ersatz_ueber_formular(pg_session, client, kunde, original):
    daten = payload(kunde, original.id)
    daten["delivery_date"] = "2026-07-08"
    r = client.post("/invoices/neu", data=daten)
    assert r.status_code == 303, r.text
    pg_session.expire_all()
    return (pg_session.query(Invoice)
            .filter(Invoice.ersetzt_invoice_id == original.id,
                    Invoice.status != "discarded").one())
