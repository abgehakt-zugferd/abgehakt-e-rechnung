"""Tests für die reine Storno-Bau-Logik (services/storno.py).

Fachliche Regeln (siehe Plan Global Constraints):
  - Storno ist eine Gutschrift mit POSITIVEN Beträgen + TypeCode 381 (via invoice_type).
  - original_invoice_id referenziert die Originalrechnung.
  - Beträge/Positionen werden 1:1 (positiv) übernommen.
  - status = draft (muss noch geprüft + finalisiert werden).
  - archive_until = 31.12. des (Ausstellungsjahr + 8), § 147 Abs. 4 AO.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceItem
from app.services.storno import build_storno


def _original() -> Invoice:
    inv = Invoice(
        invoice_number="RE-2026-001",
        customer_id=uuid.uuid4(),
        issue_date=date(2026, 6, 11),
        due_date=date(2026, 6, 25),
        delivery_date=date(2026, 6, 10),
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        net_total=Decimal("1000.00"),
        tax_total=Decimal("190.00"),
        gross_total=Decimal("1190.00"),
        status="issued",
    )
    inv.id = uuid.uuid4()
    inv.items = [
        InvoiceItem(
            position=1, description="Beratung", unit="Stunde",
            quantity=Decimal("10.0000"), unit_price=Decimal("100.0000"),
            tax_rate=Decimal("19.00"), net_amount=Decimal("1000.00"),
            tax_amount=Decimal("190.00"), gross_amount=Decimal("1190.00"),
        )
    ]
    return inv


def test_storno_has_credit_note_type_and_reference():
    original = _original()
    storno = build_storno(original, "RE-2026-002", date(2026, 7, 7))
    assert storno.invoice_type == "credit_note"
    assert storno.original_invoice_id == original.id
    assert storno.invoice_number == "RE-2026-002"
    assert storno.status == "draft"
    assert storno.customer_id == original.customer_id


def test_storno_copies_positive_amounts_and_items():
    original = _original()
    storno = build_storno(original, "RE-2026-002", date(2026, 7, 7))
    # Beträge bleiben positiv und gleich dem Original (Stornowirkung via TypeCode 381)
    assert storno.net_total == Decimal("1000.00")
    assert storno.tax_total == Decimal("190.00")
    assert storno.gross_total == Decimal("1190.00")
    # Positionen 1:1 kopiert, Menge/Preis positiv (Validator akzeptiert)
    assert len(storno.items) == 1
    item = storno.items[0]
    assert item.quantity == Decimal("10.0000")
    assert item.unit_price == Decimal("100.0000")
    assert item.net_amount == Decimal("1000.00")
    assert item.description == "Beratung"


def test_storno_sets_archive_until_eight_years_ahead():
    original = _original()
    storno = build_storno(original, "RE-2026-002", date(2026, 7, 7))
    assert storno.archive_until == date(2034, 12, 31)


def test_storno_archive_until_uses_year_end_not_issue_day():
    """Ausstellung am 29.02.: Frist endet am 31.12. des Jahres plus acht, nicht am Tag."""
    original = _original()
    storno = build_storno(original, "RE-2024-002", date(2024, 2, 29))
    assert storno.archive_until == date(2032, 12, 31)


def test_storno_profile_is_en16931():
    original = _original()
    storno = build_storno(original, "RE-2026-002", date(2026, 7, 7))
    assert storno.zugferd_profile == "EN16931"


from app.models.company import Company
from app.models.customer import Customer
from app.services import zugferd_xml
import xml.etree.ElementTree as ET

_NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}


def _company() -> Company:
    return Company(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", country="DE", vat_id="DE123456789",
    )


def test_storno_xml_has_type_code_381_and_invoice_reference():
    original = _original()
    customer = Customer(
        name="Kunde GmbH", address_line1="Weg 1", zip_code="10115",
        city="Berlin", country="DE", vat_id=None,
    )
    original.customer = customer

    storno = build_storno(original, "RE-2026-002", date(2026, 7, 7))
    storno.customer = customer
    storno.original_invoice = original  # Beziehung, die _reference_xml ausliest

    xml = zugferd_xml.generate_xml(storno, _company())
    root = ET.fromstring(xml)

    type_code = root.find(".//rsm:ExchangedDocument/ram:TypeCode", _NS)
    assert type_code is not None and type_code.text == "381"

    ref = root.find(".//ram:InvoiceReferencedDocument/ram:IssuerAssignedID", _NS)
    assert ref is not None and ref.text == "RE-2026-001"
