"""
E6 (#98): PDF↔XML-Betragskonsistenz.

Das visuelle PDF und die (seit 2025 rechtlich maßgebliche) ZUGFeRD-XML rendern
Beträge aus DERSELBEN Rechnung. Divergieren sie (Rundung, Feldwahl, Formatierung),
zeigt das PDF eine andere Rechnung als die XML — ein § 14c-Risiko (unzutreffender
Steuerausweis). Bisher prüften PDF- und XML-Tests jeweils NUR ihre eigene Seite;
eine Divergenz zwischen beiden fiel durch.

Nicht offensichtliche Divergenzfläche: der PDF-Steuerbetrag wird pro Steuersatz aus
den Positionen SUMMIERT (`tax_groups[rate]["tax"] += item.tax_amount`), die XML
`TaxTotalAmount` nutzt `invoice.tax_total`. Weichen die auseinander, zeigen PDF und
XML verschiedene Steuer.

Dieser Test extrahiert die Geldbeträge aus BEIDEN Artefakten und stellt sicher, dass
die XML-Summen (Netto/Steuer/Brutto) auch im PDF auftauchen. Er braucht weder Mustang
noch Ghostscript (ReportLab-PDF + XML-String).
"""
import re
from datetime import date
from decimal import Decimal

import pytest

import defusedxml.ElementTree as DET
from pypdf import PdfReader

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator, zugferd_xml

RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
NS = {"ram": RAM}


def _company():
    return Company(id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
                   zip_code="12345", city="Musterstadt", country="DE",
                   vat_id="DE123456789", tax_number="123/456/78901",
                   bank_iban="DE00123456780000000000")


def _invoice():
    # Beträge mit UNTERSCHIEDLICHEN Cent-Endungen, damit kein Betrag Teilstring eines
    # anderen ist (57,02 ist NICHT in 357,13 enthalten) — sonst falsch-positive Treffer.
    inv = Invoice(
        invoice_number="RE-2026-E6", issue_date=date(2026, 7, 8),
        delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22), currency="EUR",
        net_total=Decimal("300.11"), tax_total=Decimal("57.02"),
        gross_total=Decimal("357.13"), tax_category="S", zugferd_profile="EN16931",
        payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.customer = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                            zip_code="10115", city="Berlin", country="DE")
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("1"), unit_price=Decimal("300.11"),
                             tax_rate=Decimal("19"), net_amount=Decimal("300.11"),
                             tax_amount=Decimal("57.02"), gross_amount=Decimal("357.13"))]
    return inv


def _pdf_amounts(text: str) -> set:
    """Alle deutsch formatierten Geldbeträge (z. B. `1.234,56`) aus dem PDF-Text als
    Decimal. Die Lookarounds verhindern, dass `57,02` als Teil von `357,02` matcht."""
    out = set()
    for m in re.finditer(r'(?<!\d)(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})(?!\d)', text):
        out.add(Decimal(m.group(1).replace(".", "") + "." + m.group(2)))
    return out


def _xml_total(root, tag) -> Decimal:
    el = root.find(f".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:{tag}", NS)
    assert el is not None, f"{tag} fehlt in der XML"
    return Decimal(el.text)


def test_pdf_and_xml_amounts_match(tmp_path):
    inv = _invoice()
    company = _company()

    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(inv, company, out)
    pdf_text = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    pdf_amounts = _pdf_amounts(pdf_text)

    root = DET.fromstring(zugferd_xml.generate_xml(inv, company).encode("utf-8"))
    xml_net = _xml_total(root, "LineTotalAmount")
    xml_tax = _xml_total(root, "TaxTotalAmount")
    xml_gross = _xml_total(root, "GrandTotalAmount")

    # Die XML-Summen entsprechen exakt den Rechnungsfeldern (XML korrekt)…
    assert (xml_net, xml_tax, xml_gross) == (inv.net_total, inv.tax_total, inv.gross_total)
    # …und GENAU dieselben Beträge müssen im PDF stehen (PDF ≡ XML).
    assert xml_net in pdf_amounts, f"Netto {xml_net} fehlt im PDF: {sorted(pdf_amounts)}"
    assert xml_tax in pdf_amounts, f"Steuer {xml_tax} fehlt im PDF: {sorted(pdf_amounts)}"
    assert xml_gross in pdf_amounts, f"Brutto {xml_gross} fehlt im PDF: {sorted(pdf_amounts)}"


def _invoice_mixed_rates():
    inv = Invoice(
        invoice_number="RE-2026-MIX", issue_date=date(2026, 7, 8),
        delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22), currency="EUR",
        net_total=Decimal("250.00"), tax_total=Decimal("41.50"),
        gross_total=Decimal("291.50"), tax_category="S", zugferd_profile="EN16931",
        payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.customer = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                            zip_code="10115", city="Berlin", country="DE")
    inv.items = [
        InvoiceItem(position=1, description="Standard", unit="Std",
                    quantity=Decimal("2"), unit_price=Decimal("100.00"),
                    tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                    tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00")),
        InvoiceItem(position=2, description="Ermaessigt", unit="Stk",
                    quantity=Decimal("1"), unit_price=Decimal("50.00"),
                    tax_rate=Decimal("7"), net_amount=Decimal("50.00"),
                    tax_amount=Decimal("3.50"), gross_amount=Decimal("53.50")),
    ]
    return inv


def test_pdf_and_xml_amounts_match_mixed_tax_rates(tmp_path):
    """#26: gemischte Saetze 19 % + 7 % muessen in PDF und XML uebereinstimmen."""
    inv = _invoice_mixed_rates()
    company = _company()
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(inv, company, out)
    pdf_text = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    pdf_amounts = _pdf_amounts(pdf_text)
    root = DET.fromstring(zugferd_xml.generate_xml(inv, company).encode("utf-8"))
    xml_net = _xml_total(root, "LineTotalAmount")
    xml_gross = _xml_total(root, "GrandTotalAmount")
    xml_tax = _xml_total(root, "TaxTotalAmount")
    assert xml_net in pdf_amounts, f"Netto {xml_net} fehlt im PDF"
    assert xml_gross in pdf_amounts, f"Brutto {xml_gross} fehlt im PDF"
    assert xml_tax == inv.tax_total
    for item in inv.items:
        assert item.tax_amount in pdf_amounts, (
            f"Steueranteil {item.tax_rate} % ({item.tax_amount}) fehlt im PDF"
        )


@pytest.mark.parametrize("tax_category", ["E", "AE", "K", "O"])
def test_pdf_and_xml_amounts_match_steuerfreie_kategorien(tmp_path, tax_category):
    """#32: steuerfreie Kategorien, Brutto = Netto."""
    inv = _invoice()
    inv.tax_category = tax_category
    inv.tax_total = Decimal("0.00")
    inv.gross_total = inv.net_total
    for item in inv.items:
        item.tax_rate = Decimal("0")
        item.tax_amount = Decimal("0")
        item.gross_amount = item.net_amount
    if tax_category in ("AE", "K"):
        inv.customer.vat_id = "DE987654321"
    company = _company()
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(inv, company, out)
    pdf_text = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    pdf_amounts = _pdf_amounts(pdf_text)
    root = DET.fromstring(zugferd_xml.generate_xml(inv, company).encode("utf-8"))
    xml_net = _xml_total(root, "LineTotalAmount")
    xml_gross = _xml_total(root, "GrandTotalAmount")
    assert xml_net in pdf_amounts
    assert xml_gross in pdf_amounts
