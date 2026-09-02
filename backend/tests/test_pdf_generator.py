from types import SimpleNamespace
from datetime import date
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator
from app.services.pdf_generator import _document_title


def test_document_title_standard():
    assert _document_title(SimpleNamespace(invoice_type=None)) == "RECHNUNG"
    assert _document_title(SimpleNamespace(invoice_type="standard")) == "RECHNUNG"


def test_document_title_credit_note():
    assert _document_title(SimpleNamespace(invoice_type="credit_note")) == "GUTSCHRIFT"
    assert _document_title(SimpleNamespace(invoice_type="storno")) == "GUTSCHRIFT"


def test_document_title_correction():
    assert _document_title(SimpleNamespace(invoice_type="correction")) == "KORREKTURRECHNUNG"


# ─────────────────────────────────────────────────────────────────────────────
# New tests for embedding and content verification (Task 3)
# ─────────────────────────────────────────────────────────────────────────────


def _sample_company():
    return Company(
        id=1, name="Muster Handwerk GmbH",
        address_line1="Musterstraße 1", zip_code="12345", city="Musterstadt",
        email="info@example.de", phone="+49 111",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE00123456780000000000", bank_bic="ABCDDEFF", bank_name="Testbank",
    )


def _sample_customer():
    return Customer(
        name="Muster Kunde GmbH", address_line1="Kundenweg 1",
        zip_code="10115", city="Berlin", country="DE",
    )


def _sample_invoice(customer, invoice_type=None, original_invoice_id=None):
    item = InvoiceItem(
        position=1, description="Beratungsleistung", quantity=Decimal("2"),
        unit="Std", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"),
    )
    inv = Invoice(
        invoice_number="RE-2026-777", issue_date=date(2026, 7, 8),
        delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22),
        net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"), tax_category="S",
        payment_terms="Zahlbar innerhalb 14 Tagen.", notes="",
        invoice_type=invoice_type, original_invoice_id=original_invoice_id,
    )
    inv.customer = customer
    inv.items = [item]
    return inv


def _iter_font_objects(reader):
    for page in reader.pages:
        res = page.get("/Resources")
        if not res:
            continue
        fonts = res.get("/Font")
        if not fonts:
            continue
        for ref in fonts.values():
            yield ref.get_object()


def _font_is_embedded(font_obj):
    fd = font_obj.get("/FontDescriptor")
    if fd is None and "/DescendantFonts" in font_obj:
        desc = font_obj["/DescendantFonts"][0].get_object()
        fd = desc.get("/FontDescriptor")
    if fd is None:
        return False
    fd = fd.get_object()
    return any(k in fd for k in ("/FontFile", "/FontFile2", "/FontFile3"))


def test_generated_pdf_embeds_all_fonts(tmp_path):
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_sample_invoice(_sample_customer()), _sample_company(), out)
    reader = PdfReader(str(out))
    font_objs = list(_iter_font_objects(reader))
    assert font_objs, "PDF enthält keine Font-Ressourcen"
    for fo in font_objs:
        base = str(fo.get("/BaseFont", ""))
        assert _font_is_embedded(fo), f"Font nicht eingebettet: {base}"
        assert "Helvetica" not in base and "Times" not in base and "Courier" not in base, \
            f"Standard-14-Font verblieben: {base}"


def test_generated_pdf_contains_mandatory_content(tmp_path):
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_sample_invoice(_sample_customer()), _sample_company(), out)
    text = "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)
    for needle in ["RE-2026-777", "Muster Kunde GmbH", "Muster Handwerk GmbH",
                   "DE123456789", "RECHNUNG"]:
        assert needle in text, f"Pflichtinhalt fehlt im PDF: {needle}"


def test_header_ohne_doppelten_firmennamen_in_adresszeile2(tmp_path):
    """Adresszeile 2 darf den Namen nicht wiederholen (häufiger Setup-Fehler)."""
    company = _sample_company()
    company.name = "Duplikat Test GmbH"
    company.address_line2 = "Duplikat Test GmbH"
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_sample_invoice(_sample_customer()), company, out)
    text = "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages).casefold()
    # Brand-Stempel (GROSS) + Kontaktblock (normal) = genau zwei Nennungen
    assert text.count("duplikat test gmbh") == 2


def test_credit_note_pdf_shows_gutschrift_title(tmp_path):
    out = tmp_path / "storno.pdf"
    inv = _sample_invoice(_sample_customer(), invoice_type="credit_note", original_invoice_id=1)
    pdf_generator.generate_pdf(inv, _sample_company(), out)
    text = "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)
    assert "GUTSCHRIFT" in text


def test_credit_note_pdf_zeigt_gutschriftbetrag_ohne_zahlungsblock(tmp_path):
    """#18: Gutschrift darf keine Zahlungsaufforderung (IBAN/Verwendungszweck) suggerieren."""
    out = tmp_path / "storno.pdf"
    inv = _sample_invoice(_sample_customer(), invoice_type="credit_note", original_invoice_id=1)
    inv.payment_terms = "Gutschrift/Storno zur Rechnung RE-2026-001."
    pdf_generator.generate_pdf(inv, _sample_company(), out)
    text = "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)
    assert "Gutschriftbetrag" in text
    assert "Rechnungsbetrag" not in text
    assert "IBAN:" not in text
    assert "Verwendungszweck:" not in text
    assert "Gutschrift/Storno zur Rechnung RE-2026-001." in text


def test_standard_pdf_behält_zahlungsblock(tmp_path):
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_sample_invoice(_sample_customer()), _sample_company(), out)
    text = "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)
    assert "Rechnungsbetrag" in text
    assert "IBAN:" in text
    assert "Verwendungszweck:" in text


def _pdf_image_count(path: Path) -> int:
    count = 0
    for page in PdfReader(str(path)).pages:
        resources = page.get("/Resources")
        if not resources:
            continue
        xobjects = resources.get("/XObject")
        if not xobjects:
            continue
        for ref in xobjects.values():
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Image":
                count += 1
    return count


def test_standard_pdf_mit_iban_enthaelt_epc_qr(tmp_path):
    """#52: Girocode für Banking-Apps neben dem Zahlungsblock."""
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_sample_invoice(_sample_customer()), _sample_company(), out)
    text = "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)
    assert "Zum Überweisen scannen" in text
    assert _pdf_image_count(out) >= 1


def test_credit_note_pdf_ohne_epc_qr(tmp_path):
    out = tmp_path / "storno.pdf"
    inv = _sample_invoice(_sample_customer(), invoice_type="credit_note", original_invoice_id=1)
    pdf_generator.generate_pdf(inv, _sample_company(), out)
    text = "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)
    assert "Zum Überweisen scannen" not in text
    assert _pdf_image_count(out) == 0


def test_standard_pdf_ohne_iban_kein_epc_qr(tmp_path):
    company = _sample_company()
    company.bank_iban = None
    company.bank_bic = None
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_sample_invoice(_sample_customer()), company, out)
    text = "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)
    assert "Zum Überweisen scannen" not in text
    assert _pdf_image_count(out) == 0
