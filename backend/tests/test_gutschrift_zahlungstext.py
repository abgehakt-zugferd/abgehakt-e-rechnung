"""#231: Zahlungstext und Etikett im Gutschriftverfahren (389).

Oeffentliche Grenze: PDF-Text und ZUGFeRD BT-20 (Description) wirklich erzeugen.
"""
from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from app.services import pdf_generator
from app.services.zugferd_xml import generate_xml
from tests.factories import company_stub, customer_stub, validator_invoice_stub, zugferd_invoice_stub
from tests.probe_daten import IBAN_FIRMA_PROBE, IBAN_PROBE
from tests.test_zugferd_xml import _parse, _text

VORGABE_DE = "Zahlbar innerhalb von 14 Tagen nach Rechnungseingang ohne Abzug."
VORGABE_EN = "Payable within 14 days of invoice receipt without deduction."
FAELLIG = date(2026, 9, 15)


def _firma(**over):
    return company_stub(
        bank_iban=IBAN_FIRMA_PROBE,
        payment_terms_default=VORGABE_DE,
        payment_terms_default_en=VORGABE_EN,
        **over,
    )


def _kunde(**over):
    basis = dict(bank_iban=IBAN_PROBE, bank_bic="COBADEFFXXX")
    basis.update(over)
    return customer_stub(**basis)


def _beleg(art="self_billing", *, payment_terms=VORGABE_DE, document_language="de",
           customer=None, due_date=FAELLIG, **over):
    return validator_invoice_stub(
        invoice_type=art,
        payment_terms=payment_terms,
        document_language=document_language,
        customer=customer or _kunde(),
        due_date=due_date,
        issue_date=date(2026, 9, 1),
        invoice_number="RE-2026-389",
        **over,
    )


def _pdf_text(inv, company, tmp_path):
    out = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, company, out)
    return "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)


def _bt20(inv, company):
    root = _parse(generate_xml(
        zugferd_invoice_stub(
            invoice_type=inv.invoice_type,
            payment_terms=inv.payment_terms,
            document_language=getattr(inv, "document_language", "de"),
            customer=inv.customer,
            due_date=inv.due_date,
            issue_date=inv.issue_date,
            invoice_number=inv.invoice_number,
            gross_total=Decimal("107.00"),
            net_total=Decimal("100.00"),
            tax_total=Decimal("7.00"),
        ),
        company,
    ))
    return _text(root, ".//ram:SpecifiedTradePaymentTerms/ram:Description")


def test_gutschrift_zahlungstext_pdf_mit_iban(tmp_path):
    text = _pdf_text(_beleg(), _firma(), tmp_path)
    erwartet = f"Der Betrag wird bis 15.09.2026 auf das Konto {IBAN_PROBE} überwiesen."
    assert erwartet in text
    assert "Rechnungseingang" not in text


def test_gutschrift_zahlungstext_bt20_gleichlautend_mit_pdf(tmp_path):
    inv = _beleg()
    company = _firma()
    erwartet = f"Der Betrag wird bis 15.09.2026 auf das Konto {IBAN_PROBE} überwiesen."
    assert erwartet in _pdf_text(inv, company, tmp_path)
    assert _bt20(inv, company) == erwartet


def test_gutschrift_zahlungstext_ohne_iban(tmp_path):
    inv = _beleg(customer=_kunde(bank_iban=None, bank_bic=None))
    erwartet = "Der Betrag wird bis 15.09.2026 überwiesen."
    text = _pdf_text(inv, _firma(), tmp_path)
    assert erwartet in text
    assert IBAN_PROBE not in text
    assert _bt20(inv, _firma()) == erwartet


def test_rechnung_zahlungstext_unveraendert(tmp_path):
    inv = _beleg(art=None, payment_terms=VORGABE_DE)
    text = _pdf_text(inv, _firma(), tmp_path)
    assert VORGABE_DE in text
    assert "Der Betrag wird bis" not in text
    assert _bt20(inv, _firma()) == VORGABE_DE


def test_freier_zahlungstext_nicht_ueberschrieben(tmp_path):
    frei = "Auszahlung nach interner Freigabe, Sondervereinbarung."
    inv = _beleg(payment_terms=frei)
    text = _pdf_text(inv, _firma(), tmp_path)
    assert frei in text
    assert "Der Betrag wird bis" not in text
    assert _bt20(inv, _firma()) == frei


def test_gutschriftnummer_etikett_pdf(tmp_path):
    text = _pdf_text(_beleg(), _firma(), tmp_path)
    assert "Gutschriftnummer" in text
    assert "Rechnungsnummer" not in text


def test_rechnung_behaelt_rechnungsnummer_etikett(tmp_path):
    text = _pdf_text(_beleg(art=None), _firma(), tmp_path)
    assert "Rechnungsnummer" in text
    assert "Gutschriftnummer" not in text


def test_gutschrift_zahlungstext_en_mit_iban(tmp_path):
    inv = _beleg(payment_terms=VORGABE_EN, document_language="en")
    text = _pdf_text(inv, _firma(), tmp_path)
    erwartet = f"The amount will be transferred by 2026-09-15 to account {IBAN_PROBE}."
    assert erwartet in text
    assert _bt20(inv, _firma()) == erwartet
