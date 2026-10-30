"""Bausteine der Schlussrechnungstests (verrechnete Anzahlungen, BT-113, BG-3)."""
import json
import uuid
from datetime import date
from decimal import Decimal

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem

DATUM_ANZAHLUNG = date(2026, 7, 8)


def kunde(pg_session, name="Probe Kunde GmbH", *, country="DE", vat_id=None):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
                 address_line1="Weg 1", zip_code="80331", city="Muenchen",
                 country=country, vat_id=vat_id)
    pg_session.add(c)
    pg_session.flush()
    return c


def anzahlung(pg_session, kunde, *, netto="100.00", satz="19", kategorie="S",
              invoice_type="prepayment", status="paid", currency="EUR",
              bezahlt=True):
    """Gestellter (und standardmaessig bezahlter) Beleg, der verrechnet werden soll."""
    netto = Decimal(netto)
    steuer = (netto * Decimal(satz) / 100).quantize(Decimal("0.01"))
    inv = Invoice(
        invoice_number=f"AZ-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
        issue_date=DATUM_ANZAHLUNG, due_date=date(2026, 7, 22),
        delivery_date=DATUM_ANZAHLUNG, currency=currency, tax_category=kategorie,
        status=status, invoice_type=invoice_type,
        bezahlt_am=date(2026, 7, 15) if bezahlt else None,
        net_total=netto, tax_total=steuer, gross_total=netto + steuer,
        payment_terms="Zahlbar sofort.",
    )
    inv.items = [InvoiceItem(
        position=1, description="Anzahlung", unit="Stunde", quantity=Decimal("1"),
        unit_price=netto, tax_rate=Decimal(satz), net_amount=netto,
        tax_amount=steuer, gross_amount=netto + steuer)]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def payload(kunde, anzahlungen, *, netto="200", satz="19", kategorie="S"):
    return {
        "customer_id": str(kunde.id),
        "issue_date": "2026-08-10",
        "due_date": "2026-08-24",
        "delivery_date": "2026-08-01",
        "tax_category": kategorie,
        "payment_terms": "Zahlbar in 14 Tagen.",
        "anzahlung_ids": [str(a.id) for a in anzahlungen],
        "items_json": json.dumps([{"description": "Beratung", "unit": "Stunde",
                                   "quantity": "1", "unit_price": netto,
                                   "tax_rate": satz}]),
    }


def schluss_ueber_formular(pg_session, client, kunde, anzahlungen, **kw):
    r = client.post("/invoices/neu", data=payload(kunde, anzahlungen, **kw))
    assert r.status_code == 303, r.text
    pg_session.expire_all()
    return (pg_session.query(Invoice)
            .filter(Invoice.customer_id == kunde.id, Invoice.status == "draft",
                    Invoice.invoice_type.is_(None)).order_by(Invoice.created_at.desc())
            .first())
