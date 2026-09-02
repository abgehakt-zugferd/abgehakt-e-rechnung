"""Gemeinsame Test-Stubs und ORM-Fabriken (#40).

Eine Quelle fuer _company/_customer/_invoice in Validator-, ZUGFeRD- und
Schema-Tests. Fehlende Felder an einem Stub sollen nicht mehr als
AttributeError in einer Datei und fachliche Assertion in einer anderen enden.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from types import SimpleNamespace

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from tests.probe_daten import IBAN_FIRMA_PROBE, UST_DE_PROBE, UST_DE_PROBE_2

# Felder, die SimpleNamespace-Stubs fuer Validator und ZUGFeRD-Generator tragen muessen.
COMPANY_STUB_FIELDS = (
    "name", "address_line1", "address_line2", "zip_code", "city", "country",
    "tax_number", "vat_id", "vat_id_checked_at", "vat_id_check_valid", "vat_id_vies_name", "vat_id_name_match",
    "email", "phone", "contact_name", "bank_iban", "bank_bic",
)
CUSTOMER_STUB_FIELDS = (
    "name", "address_line1", "address_line2", "zip_code", "city", "country",
    "vat_id", "vat_id_checked_at", "vat_id_check_valid", "vat_id_vies_name", "vat_id_name_match",
    "email", "bank_iban", "bank_bic", "bank_name",
)
ITEM_STUB_FIELDS = (
    "position", "description", "unit", "quantity", "unit_price", "tax_rate",
    "net_amount", "tax_amount", "gross_amount",
)
INVOICE_STUB_FIELDS = (
    "invoice_number", "issue_date", "due_date", "delivery_date", "payment_terms",
    "notes", "currency", "net_total", "tax_total", "gross_total", "status",
    "customer", "items", "tax_category", "zugferd_profile", "invoice_type",
    "original_invoice_id", "original_invoice",
)


def _stub(defaults: dict, **kwargs):
    merged = defaults.copy()
    merged.update(kwargs)
    if merged.get("vat_id") and merged.get("vat_id_checked_at") is None:
        merged["vat_id_checked_at"] = datetime.now(timezone.utc)
        merged.setdefault("vat_id_check_valid", True)
        merged.setdefault("vat_id_name_match", "unbekannt")
        merged.setdefault("vat_id_vies_name", None)
    return SimpleNamespace(**merged)


def company_stub(**kwargs):
    return _stub(dict(
        name="Muster Handwerk GmbH",
        address_line1="Musterstraße 1",
        address_line2=None,
        zip_code="12345",
        city="Musterstadt",
        country="DE",
        tax_number="12/345/67890",
        vat_id=None,
        vat_id_checked_at=None,
        vat_id_check_valid=None,
        vat_id_vies_name=None,
        vat_id_name_match=None,
        email=None,
        phone=None,
        contact_name=None,
        bank_iban=None,
        bank_bic=None,
    ), **kwargs)


def customer_stub(**kwargs):
    return _stub(dict(
        name="Muster GmbH",
        address_line1="Hauptstraße 10",
        address_line2=None,
        zip_code="80331",
        city="München",
        country="DE",
        vat_id=None,
        vat_id_checked_at=None,
        vat_id_check_valid=None,
        vat_id_vies_name=None,
        vat_id_name_match=None,
        email=None,
        bank_iban=None,
        bank_bic=None,
        bank_name=None,
    ), **kwargs)


def item_stub(**kwargs):
    return _stub(dict(
        position=1,
        description="Beratungsleistung",
        unit="Stunde",
        quantity=Decimal("2.0000"),
        unit_price=Decimal("100.00"),
        tax_rate=Decimal("19.00"),
        net_amount=Decimal("200.00"),
        tax_amount=Decimal("38.00"),
        gross_amount=Decimal("238.00"),
    ), **kwargs)


def validator_invoice_stub(**kwargs):
    return _stub(dict(
        invoice_number="RE-2026-001",
        issue_date=date(2026, 6, 11),
        due_date=date(2026, 6, 25),
        delivery_date=date(2026, 6, 11),
        payment_terms="Zahlbar innerhalb 14 Tagen.",
        notes=None,
        currency="EUR",
        net_total=Decimal("200.00"),
        tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"),
        status="draft",
        customer=customer_stub(),
        items=[item_stub()],
        tax_category="S",
        zugferd_profile="EN16931",
        invoice_type=None,
        original_invoice_id=None,
        original_invoice=None,
    ), **kwargs)


def zugferd_invoice_stub(**kwargs):
    return _stub(dict(
        invoice_number="RE-2026-001",
        issue_date=date(2026, 6, 11),
        due_date=date(2026, 6, 25),
        delivery_date=None,
        payment_terms="Zahlbar innerhalb 14 Tagen.",
        notes=None,
        currency="EUR",
        net_total=Decimal("200.00"),
        tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"),
        status="draft",
        zugferd_profile="EN16931",
        customer=customer_stub(),
        items=[item_stub()],
        tax_category="S",
        invoice_type=None,
        original_invoice_id=None,
        original_invoice=None,
    ), **kwargs)


def orm_company(**over) -> Company:
    kw = dict(
        id=1,
        name="Muster Handwerk GmbH",
        address_line1="Musterstraße 1",
        zip_code="12345",
        city="Musterstadt",
        country="DE",
        tax_number="123/456/78901",
        vat_id=UST_DE_PROBE,
        email="info@example.de",
        phone="+49 111",
        bank_iban=IBAN_FIRMA_PROBE,
        bank_bic="ABCDDEFF",
        bank_name="Testbank",
    )
    kw.update(over)
    if kw.get("vat_id") and kw.get("vat_id_checked_at") is None and "vat_id_checked_at" not in over:
        kw["vat_id_checked_at"] = datetime.now(timezone.utc)
        kw.setdefault("vat_id_check_valid", True)
        kw.setdefault("vat_id_name_match", "unbekannt")
    return Company(**kw)


def orm_customer(**over) -> Customer:
    kw = dict(
        name="Kunde GmbH",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        vat_id=UST_DE_PROBE_2,
    )
    kw.update(over)
    if kw.get("vat_id") and kw.get("vat_id_checked_at") is None and "vat_id_checked_at" not in over:
        kw["vat_id_checked_at"] = datetime.now(timezone.utc)
        kw.setdefault("vat_id_check_valid", True)
        kw.setdefault("vat_id_name_match", "unbekannt")
    return Customer(**kw)


def orm_item(pos, qty, price, rate, *, unit="Stk", description="Leistung"):
    net = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    tax = (net * Decimal(rate) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return InvoiceItem(
        position=pos,
        description=description,
        unit=unit,
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        tax_rate=Decimal(rate),
        net_amount=net,
        tax_amount=tax,
        gross_amount=net + tax,
    )


def orm_invoice(items, *, net=None, tax=None, gross=None, tax_category="S", **over):
    net = net if net is not None else sum(i.net_amount for i in items)
    tax = tax if tax is not None else sum(i.tax_amount for i in items)
    gross = gross if gross is not None else net + tax
    kw = dict(
        invoice_number="RE-2026-001",
        issue_date=date(2026, 6, 1),
        due_date=date(2026, 6, 15),
        currency="EUR",
        net_total=net,
        tax_total=tax,
        gross_total=gross,
        tax_category=tax_category,
        payment_terms="14 Tage",
    )
    kw.update(over)
    inv = Invoice(**kw)
    inv.customer = kw.get("customer") or orm_customer()
    inv.items = items
    return inv


def orm_invoice_for(customer: Customer, **over) -> Invoice:
    item = orm_item(1, "2", "100.00", "19", unit="Std", description="Beratungsleistung")
    kw = dict(
        invoice_number="RE-2026-778",
        issue_date=date(2026, 7, 8),
        delivery_date=date(2026, 7, 8),
        due_date=date(2026, 7, 22),
        currency="EUR",
        net_total=Decimal("200.00"),
        tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"),
        tax_category="S",
        payment_terms="Zahlbar innerhalb 14 Tagen.",
        notes="",
    )
    kw.update(over)
    inv = Invoice(**kw)
    inv.customer = customer
    inv.items = over.get("items") or [item]
    return inv
