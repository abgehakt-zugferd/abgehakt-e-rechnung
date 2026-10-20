"""Bausteine fuer tests/test_belegart_alias.py: Belege ohne Firmen-Setup."""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services import auftragsschluessel


def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def kunde(pg_session):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Kunde GmbH",
        address_line1="Weg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def beleg(pg_session, *, status="issued", art=None, original=None,
          netto="100.00", steuer="19.00", ausgestellt=date(2026, 5, 1),
          faellig=date(2026, 5, 15), schluessel=None):
    k = kunde(pg_session)
    netto_d, steuer_d = Decimal(netto), Decimal(steuer)
    inv = Invoice(
        invoice_number=f"RE-GP-{uuid.uuid4().hex[:6]}",
        customer_id=k.id,
        issue_date=ausgestellt,
        due_date=faellig,
        currency="EUR",
        tax_category="S",
        status=status,
        invoice_type=art,
        original_invoice_id=original.id if original else None,
        net_total=netto_d,
        tax_total=steuer_d,
        gross_total=netto_d + steuer_d,
    )
    if schluessel:
        auftragsschluessel.belegen(inv, schluessel)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def gutschrift(pg_session, original, *, art="credit_note", status="issued",
               ausgestellt=None):
    return beleg(
        pg_session,
        status=status,
        art=art,
        original=original,
        netto=str(original.net_total),
        steuer=str(original.tax_total),
        ausgestellt=ausgestellt or original.issue_date,
        faellig=ausgestellt or original.issue_date,
    )


def leere_firma(pg_session):
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    firma.setup_completed_at = None
    firma.name = ""
    firma.address_line1 = ""
    firma.zip_code = ""
    firma.city = ""
    firma.tax_number = None
    firma.vat_id = None
    pg_session.commit()
    return firma


def kunde_mit_positionen(pg_session):
    """Kunde fuer Storno-/Guard-Pfade (Beleg mit Position separat anlegen)."""
    return kunde(pg_session)


def beleg_mit_position(
    pg_session, kunde_obj, *, status="issued", invoice_type=None, original=None,
):
    from app.models.invoice import InvoiceItem

    inv = Invoice(
        invoice_number=f"RE-BA-{uuid.uuid4().hex[:6]}",
        customer_id=kunde_obj.id,
        issue_date=date(2026, 6, 1),
        due_date=date(2026, 6, 15),
        delivery_date=date(2026, 6, 1),
        currency="EUR",
        tax_category="S",
        status=status,
        invoice_type=invoice_type,
        original_invoice_id=original.id if original else None,
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.items = [InvoiceItem(
        position=1, description="Beratung", unit="Stunde",
        quantity=Decimal("1"), unit_price=Decimal("100.00"),
        tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
        tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"),
    )]
    pg_session.add(inv)
    pg_session.commit()
    return inv
