from datetime import date
from decimal import Decimal

import pytest

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, pdf_generator, pdfa, zugferd_xml


def _company():
    return Company(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", email="info@example.de", phone="+49 111",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE00123456780000000000", bank_bic="ABCDDEFF", bank_name="Testbank",
        country="DE",
    )


def _invoice():
    cust = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                    zip_code="10115", city="Berlin", country="DE")
    item = InvoiceItem(position=1, description="Beratungsleistung", quantity=Decimal("2"),
                       unit="Std", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
                       net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"))
    inv = Invoice(invoice_number="RE-2026-778", issue_date=date(2026, 7, 8),
                  delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22),
                  currency="EUR",  # DB-Default; auf dem transienten Objekt explizit setzen
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"), tax_category="S",
                  payment_terms="Zahlbar innerhalb 14 Tagen.", notes="")
    inv.customer = cust
    inv.items = [item]
    return inv


@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
def test_branded_pdf_passes_pdfa_validation(tmp_path):
    """Volle Pipeline: gebrandetes ReportLab-PDF → PDF/A-3 (Ghostscript) →
    Mustang bettet ZUGFeRD-XML ein → Mustang-Validierung ist grün
    (Parsed PDF:valid XML:valid)."""
    company, invoice = _company(), _invoice()
    visual = tmp_path / "visual.pdf"
    pdf_generator.generate_pdf(invoice, company, visual)

    pdfa_pdf = tmp_path / "pdfa.pdf"
    assert pdfa.to_pdfa3(visual, pdfa_pdf, title=invoice.invoice_number), \
        "Ghostscript PDF/A-3-Konvertierung ist fehlgeschlagen"

    xml_path = tmp_path / "invoice.xml"
    xml_path.write_text(zugferd_xml.generate_xml(invoice, company), encoding="utf-8")

    combined = tmp_path / "zugferd.pdf"
    assert mustang.combine(pdfa_pdf, xml_path, combined), "Mustang combine ist fehlgeschlagen"

    result = mustang.validate(combined)
    assert result["is_valid"], f"PDF/A-Validierung rot:\n{result['raw']}"
