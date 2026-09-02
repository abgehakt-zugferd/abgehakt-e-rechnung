"""Kunden-Bankverbindung und Gutschrift-EPC-QR."""

from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator
from app.services.bankverbindung import normalisiere_iban, pruefe_iban
from app.services.validator import validate_invoice
from app.services.zugferd_xml import generate_xml
from tests.factories import company_stub, customer_stub, validator_invoice_stub, zugferd_invoice_stub
from tests.probe_daten import IBAN_FIRMA_PROBE, IBAN_PROBE, IBAN_PROBE_SPACED
from tests.test_zugferd_xml import _parse, _text


def test_normalisiere_iban_entfernt_leerzeichen():
    assert normalisiere_iban(IBAN_PROBE_SPACED) == IBAN_PROBE


def test_pruefe_iban_lehnt_ungueltig_ab():
    assert pruefe_iban("falsch") is not None


def test_self_billing_pdf_mit_kunden_iban_epc_qr(tmp_path):
    company = company_stub(bank_iban=IBAN_FIRMA_PROBE)
    customer = Customer(
        name="Autor Auszahlung",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        customer_number="T-001",
        bank_iban=IBAN_PROBE,
        bank_bic="COBADEFFXXX",
        bank_name="Commerzbank",
    )
    item = InvoiceItem(
        position=1,
        description="Beteiligung",
        quantity=Decimal("1"),
        unit="Pauschal",
        unit_price=Decimal("100.00"),
        tax_rate=Decimal("7"),
        net_amount=Decimal("100.00"),
        tax_amount=Decimal("7.00"),
        gross_amount=Decimal("107.00"),
    )
    inv = Invoice(
        invoice_number="RE-2026-389",
        issue_date=date(2026, 9, 1),
        due_date=date(2026, 9, 15),
        delivery_date=date(2026, 8, 31),
        net_total=Decimal("100.00"),
        tax_total=Decimal("7.00"),
        gross_total=Decimal("107.00"),
        tax_category="S",
        invoice_type="self_billing",
    )
    inv.customer = customer
    inv.items = [item]

    out = tmp_path / "gutschrift.pdf"
    pdf_generator.generate_pdf(inv, company, out)
    text = "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)
    assert IBAN_PROBE in text
    assert "Zum Überweisen scannen" in text
    assert "Gutschriftbetrag auf die unten genannte Bankverbindung" in text


def test_self_billing_zugferd_traegt_kunden_iban():
    company = company_stub(bank_iban=IBAN_FIRMA_PROBE)
    customer = customer_stub(
        bank_iban=IBAN_PROBE,
        bank_bic="COBADEFFXXX",
    )
    inv = zugferd_invoice_stub(
        customer=customer,
        invoice_type="self_billing",
        gross_total=Decimal("107.00"),
        net_total=Decimal("100.00"),
        tax_total=Decimal("7.00"),
    )
    root = _parse(generate_xml(inv, company))
    pm = ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementPaymentMeans"
    assert _text(root, f"{pm}/ram:PayeePartyCreditorFinancialAccount/ram:IBANID") == IBAN_PROBE


def test_validator_warns_ohne_kunden_iban_bei_self_billing():
    company = company_stub()
    inv = validator_invoice_stub(invoice_type="self_billing", customer=customer_stub(bank_iban=None))
    _, warnings = validate_invoice(inv, company)
    codes = {w.code for w in warnings}
    assert "CUSTOMER_BANK_MISSING" in codes
