"""
E8 (#98): Das kombinierte ZUGFeRD-PDF muss die eingebettete Factur-X-XML korrekt als
**Associated File** deklarieren — `/AFRelationship = /Alternative` (Factur-X/EN16931:
die XML ist die maßgebliche Alternative zum visuellen PDF, kein bloßer Anhang) — und das
Factur-X-XMP tragen. Ein Empfänger-/Prüfsystem, das die XML über `/AF` sucht, findet sie
sonst nicht bzw. wertet sie als Datenanhang statt als E-Rechnung. Bisher prüfte kein Test
diese Deklaration; `mustang.validate` (is_valid + XML:valid) belegt sie nicht sichtbar.

Voller Pipeline-Lauf (ReportLab → PDF/A-3 (Ghostscript) → mustang.combine), danach
Inspektion mit pypdf. Skippt ohne Mustang-JAR/Ghostscript.
"""
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, pdfa, pdf_generator, zugferd_xml

pytestmark = pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)


def _company():
    return Company(id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
                   zip_code="12345", city="Musterstadt", country="DE",
                   tax_number="123/456/78901", vat_id="DE123456789",
                   bank_iban="DE00123456780000000000")


def _invoice():
    inv = Invoice(invoice_number="RE-2026-AF8", issue_date=date(2026, 7, 8),
                  delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22), currency="EUR",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"), tax_category="S", zugferd_profile="EN16931",
                  payment_terms="Zahlbar in 14 Tagen.")
    inv.customer = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                            zip_code="10115", city="Berlin", country="DE")
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("2"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                             tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))]
    return inv


def _combined_pdf(tmp_path):
    inv, company = _invoice(), _company()
    visual = tmp_path / "visual.pdf"
    pdf_generator.generate_pdf(inv, company, visual)
    pdfa_pdf = tmp_path / "pdfa.pdf"
    assert pdfa.to_pdfa3(visual, pdfa_pdf, title=inv.invoice_number)
    xml_in = tmp_path / "in.xml"
    xml_in.write_text(zugferd_xml.generate_xml(inv, company), encoding="utf-8")
    out = tmp_path / "zugferd.pdf"
    assert mustang.combine(pdfa_pdf, xml_in, out)
    return out


def test_embedded_xml_is_associated_file_with_relationship_alternative(tmp_path):
    root = PdfReader(str(_combined_pdf(tmp_path))).trailer["/Root"]
    af = root.get("/AF")
    assert af is not None, "PDF-Katalog hat kein /AF (Associated Files) — XML nicht als AF deklariert"

    specs = [s.get_object() for s in af]
    seen = [(str(s.get("/F") or s.get("/UF")), str(s.get("/AFRelationship"))) for s in specs]
    xml_alt = [s for s in specs
               if str(s.get("/F") or s.get("/UF") or "").lower().endswith(".xml")
               and str(s.get("/AFRelationship")) == "/Alternative"]
    assert xml_alt, f"kein XML-Filespec mit /AFRelationship=/Alternative; /AF enthält: {seen}"


def test_xmp_metadata_declares_facturx(tmp_path):
    root = PdfReader(str(_combined_pdf(tmp_path))).trailer["/Root"]
    meta = root.get("/Metadata")
    assert meta is not None, "PDF hat keine /Metadata (XMP) — Factur-X-Deklaration fehlt"
    xmp = meta.get_object().get_data().decode("utf-8", "replace").lower()
    # Factur-X-XMP-Erweiterung deklariert den Dokumenttyp/das Profil; Mustang schreibt
    # den factur-x/zugferd-Namespace ins XMP. Robust gegen Varianten der Schreibweise.
    assert ("factur-x" in xmp or "facturx" in xmp or "zugferd" in xmp), (
        "XMP nennt weder factur-x noch zugferd — Factur-X-Metadaten fehlen"
    )
