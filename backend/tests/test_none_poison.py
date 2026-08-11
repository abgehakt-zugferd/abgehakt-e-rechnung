"""
E9 (#98): Python-`None` in einem nullbaren Feld darf NIE als Literalstring „None" in
der ZUGFeRD-XML oder im PDF landen (Vorfall 2026-07-08: `address_line2` erschien als
echte Adresszeile „None"). Die Generatoren müssen None zu leer machen — `_esc()` gibt
für falsy "" zurück, das PDF kapselt jedes optionale Feld in ein `if feld:`.

Regression: eine Rechnung mit ALLEN optionalen Feldern = None erzeugen und sicherstellen,
dass weder die (rechtlich maßgebliche) XML noch das PDF den Token „None" enthalten.

Break-and-Revert: ein Feld auf den STRING "None" gesetzt (der truthy die `if feld:`-
Guards passiert — genau das Vorfallmuster) ⇒ Assertion ROT.
"""
from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator, zugferd_xml


def _company():
    # nullbare Felder bewusst None: address_line2, vat_id, phone, email, bank_bic
    return Company(id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
                   address_line2=None, zip_code="12345", city="Musterstadt", country="DE",
                   tax_number="123/456/78901", vat_id=None, email=None, phone=None,
                   bank_iban="DE00123456780000000000", bank_bic=None, bank_name=None)


def _customer():
    return Customer(customer_number=None, name="Muster Kunde GmbH",
                    address_line1="Kundenweg 1", address_line2=None, zip_code="10115",
                    city="Berlin", country="DE", vat_id=None, email=None, phone=None,
                    notes=None)


def _invoice():
    inv = Invoice(invoice_number="RE-2026-N9", issue_date=date(2026, 7, 8),
                  delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22), currency="EUR",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"), tax_category="S", zugferd_profile="EN16931",
                  payment_terms="Zahlbar in 14 Tagen.", notes=None)
    inv.customer = _customer()
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("2"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                             tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))]
    return inv


def test_none_optionals_produce_no_none_literal_in_xml():
    xml = zugferd_xml.generate_xml(_invoice(), _company())
    assert "None" not in xml, "Literal 'None' in der ZUGFeRD-XML — None-Poison im XML-Generator"


def test_none_optionals_produce_no_none_literal_in_pdf(tmp_path):
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_invoice(), _company(), out)
    text = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    assert "None" not in text, "Literal 'None' im PDF — None-Poison im PDF-Generator"
