"""#231: Zahlungstext und Etikett im Gutschriftverfahren (389).

Oeffentliche Grenze: PDF-Text und ZUGFeRD BT-20 (Description) wirklich erzeugen.
Ersetzung nur beim Speichern/Finalisieren, nicht beim Rendern (GoBD).
"""
from datetime import date
from decimal import Decimal
import uuid

from pypdf import PdfReader

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator
from app.services.belegsprache import darstellung
from app.services.zugferd_xml import generate_xml
from tests.factories import company_stub, customer_stub, validator_invoice_stub, zugferd_invoice_stub
from tests.probe_daten import IBAN_FIRMA_PROBE, IBAN_PROBE
from tests.test_zugferd_xml import _parse, _text

VORGABE_DE = "Zahlbar innerhalb von 14 Tagen nach Rechnungseingang ohne Abzug."
VORGABE_EN = "Payable within 14 days of invoice receipt without deduction."
FAELLIG = date(2026, 9, 15)
NEU_DE = f"Der Betrag wird bis 15.09.2026 auf das Konto {IBAN_PROBE} überwiesen."
NEU_DE_OHNE = "Der Betrag wird bis 15.09.2026 überwiesen."
NEU_EN = f"The amount will be transferred by 2026-09-15 to account {IBAN_PROBE}."


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


def _beleg(art="self_billing", *, payment_terms=NEU_DE, document_language="de",
           customer=None, due_date=FAELLIG, status="draft", **over):
    return validator_invoice_stub(
        invoice_type=art,
        payment_terms=payment_terms,
        document_language=document_language,
        customer=customer or _kunde(),
        due_date=due_date,
        issue_date=date(2026, 9, 1),
        invoice_number="RE-2026-389",
        status=status,
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
    assert NEU_DE in text
    assert "Rechnungseingang" not in text


def test_gutschrift_zahlungstext_bt20_gleichlautend_mit_pdf(tmp_path):
    inv = _beleg()
    company = _firma()
    assert NEU_DE in _pdf_text(inv, company, tmp_path)
    assert _bt20(inv, company) == NEU_DE


def test_gutschrift_zahlungstext_ohne_iban(tmp_path):
    inv = _beleg(
        payment_terms=NEU_DE_OHNE,
        customer=_kunde(bank_iban=None, bank_bic=None),
    )
    text = _pdf_text(inv, _firma(), tmp_path)
    assert NEU_DE_OHNE in text
    assert IBAN_PROBE not in text
    assert _bt20(inv, _firma()) == NEU_DE_OHNE


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
    inv = _beleg(payment_terms=NEU_EN, document_language="en")
    text = _pdf_text(inv, _firma(), tmp_path)
    assert NEU_EN in text
    assert _bt20(inv, _firma()) == NEU_EN


def test_gestellte_gutschrift_mit_vorgabe_rendert_unveraendert(tmp_path):
    """GoBD: issued mit altem Vorgabetext darf beim erneuten Rendern nicht kippen."""
    inv = _beleg(payment_terms=VORGABE_DE, status="issued")
    company = _firma()
    text = _pdf_text(inv, company, tmp_path)
    assert VORGABE_DE in text
    assert "Der Betrag wird bis" not in text
    assert _bt20(inv, company) == VORGABE_DE


def test_alter_entwurf_bekommt_neuen_text_beim_finalisieren(pg_session):
    """Entwurf mit Firmenvorgabe: Finalisieren persistiert den Gutschrift-Text."""
    from tests.helpers.finalize_pipeline import cleanup, finalize_with_fake_pipeline

    company = pg_session.query(Company).filter(Company.id == 1).one()
    company.payment_terms_default = VORGABE_DE
    company.payment_terms_default_en = VORGABE_EN
    company.bank_iban = IBAN_FIRMA_PROBE
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Leistender Probe",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        gutschriftempfaenger=True,
        ust_status="regelbesteuert",
        tax_number="12/345/67890",
        bank_iban=IBAN_PROBE,
        bank_bic="COBADEFFXXX",
    )
    pg_session.add(kunde)
    pg_session.flush()
    faellig = date(2026, 9, 15)
    nummer = f"HG-{uuid.uuid4().hex[:6]}"
    inv = Invoice(
        invoice_number=nummer,
        customer_id=kunde.id,
        issue_date=date(2026, 9, 1),
        delivery_date=date(2026, 8, 31),
        due_date=faellig,
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        invoice_type="self_billing",
        status="draft",
        payment_terms=VORGABE_DE,
        net_total=Decimal("100.00"),
        tax_total=Decimal("7.00"),
        gross_total=Decimal("107.00"),
    )
    inv.items = [
        InvoiceItem(
            position=1,
            description="Beteiligung",
            unit="Stück",
            quantity=Decimal("1"),
            unit_price=Decimal("100.00"),
            tax_rate=Decimal("7"),
            net_amount=Decimal("100.00"),
            tax_amount=Decimal("7.00"),
            gross_amount=Decimal("107.00"),
        )
    ]
    pg_session.add(inv)
    pg_session.commit()

    try:
        antwort = finalize_with_fake_pipeline(pg_session, inv.id)
        assert antwort.status_code == 303, antwort.text
    finally:
        cleanup(nummer)

    pg_session.expire_all()
    gestellt = pg_session.get(Invoice, inv.id)
    assert gestellt.status == "issued"
    erwartet = darstellung("de").zahlung_gutschriftverfahren(
        datum=gestellt.due_date, iban=IBAN_PROBE,
    )
    assert gestellt.payment_terms == erwartet
    assert VORGABE_DE not in (gestellt.payment_terms or "")
    assert "Der Betrag wird bis" in gestellt.payment_terms
    assert IBAN_PROBE in gestellt.payment_terms
    assert erwartet in (gestellt.zugferd_xml or "")
