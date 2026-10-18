"""Kopftext und Fusstext im Rechnungs-PDF (Bauschritt 2a).

Kopftext steht als Absatz UEBER der Positionstabelle, Fusstext UNTER dem
Summenblock. Beide gehen durch dieselbe Aufbereitung wie Positionsbeschreibungen
(``_description_markup``: erst escapen, dann Zeilenumbrueche) — sonst waere ein
``<b`` im Kundentext ein fettes Tag statt Text. Leer druckt nichts.
"""
from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator


def _company():
    return Company(
        id=1, name="Muster Handwerk GmbH",
        address_line1="Musterstraße 1", zip_code="12345", city="Musterstadt",
        email="info@example.de", phone="+49 111",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE33PROBE0000000000001", bank_bic="ABCDDEFF", bank_name="Testbank",
    )


def _invoice(kopftext=None, fusstext=None):
    item = InvoiceItem(
        position=1, description="Beratung September", quantity=Decimal("2"),
        unit="Stunde", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"),
        gross_amount=Decimal("238.00"),
    )
    inv = Invoice(
        invoice_number="RE-2026-888", issue_date=date(2026, 10, 5),
        delivery_date=date(2026, 10, 5), due_date=date(2026, 10, 19),
        net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"), tax_category="S",
        payment_terms="Zahlbar innerhalb 14 Tagen.", notes="",
        kopftext=kopftext, fusstext=fusstext,
    )
    inv.customer = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                            zip_code="10115", city="Berlin", country="DE")
    inv.items = [item]
    return inv


def _text(pdf_path):
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)


def test_kopftext_oberhalb_und_fusstext_unterhalb(tmp_path):
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(
        _invoice(kopftext="Vertragsgrundlage Plattformvertrag",
                 fusstext="Der Auszahlungsbericht ist Einzelaufstellung."),
        _company(), out,
    )
    text = _text(out)
    flach = text.replace("\n", " ")
    assert "Vertragsgrundlage Plattformvertrag" in flach
    assert "Einzelaufstellung" in flach
    # Reihenfolge gegen den erzeugten Text: Kopf vor der Position, Fuss nach
    # dem Summenblock (Label aus der Belegdarstellung, deutsch).
    assert text.index("Vertragsgrundlage") < text.index("Beratung September")
    assert text.index("Einzelaufstellung") > text.index("Rechnungsbetrag")


def test_umbruch_und_escaping_wie_bei_beschreibungen(tmp_path):
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(
        _invoice(kopftext="Zeile eins\nZeile zwei <b>kein</b> Markup",
                 fusstext="Fuss <10 Stueck & mehr"),
        _company(), out,
    )
    flach = _text(out).replace("\n", " ")
    assert "Zeile eins" in flach
    assert "Zeile zwei" in flach
    assert "<b>kein</b> Markup" in flach, "Markup muss escaped als Text stehen"
    assert "<10 Stueck & mehr" in flach


def test_leer_heisst_nichts_drucken(tmp_path):
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_invoice(kopftext=None, fusstext=None), _company(), out)
    text = _text(out)
    # Kein NULL-Text: leere Spalten duerfen keine Spur hinterlassen.
    assert "None" not in text
