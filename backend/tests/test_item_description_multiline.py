"""
Mehrzeilige Positionsbeschreibungen (#142, Spec 2026-07-31).

Was man tippt, ist was rausgeht: der Text landet vollständig und mit Umbrüchen in
`ram:Name` (BT-153) der CII-XML. Keine Sonderrolle der ersten Zeile, keine Aufteilung
auf BT-154.

Drei Konsumenten müssen mitziehen — XML, PDF und die Detailseite. Der PDF-Teil deckt
zugleich eine **bestehende** Regression ab: `pdf_generator` gibt die Beschreibung roh
an `Paragraph`, und `Paragraph` interpretiert Mini-HTML. Empirisch geprüft (2026-08-03,
ReportLab im Container): `&` und `<10 Stueck>` gehen durch, aber ein `<` gefolgt von
einem Buchstaben (`5<x`) wirft `ValueError: unclosed tags` — die PDF-Erzeugung bricht
also schon heute an einer harmlosen Beschreibung.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator, zugferd_xml


def teardown_function():
    app.dependency_overrides.clear()


def _company():
    return Company(
        id=1, name="Muster Handwerk GmbH",
        address_line1="Musterstraße 1", zip_code="12345", city="Musterstadt",
        email="info@example.de", phone="+49 111",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE00123456780000000000", bank_bic="ABCDDEFF", bank_name="Testbank",
    )


def _invoice(description):
    item = InvoiceItem(
        position=1, description=description, quantity=Decimal("2"),
        unit="Std", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"),
        gross_amount=Decimal("238.00"),
    )
    inv = Invoice(
        invoice_number="RE-2026-777", issue_date=date(2026, 7, 8),
        delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22),
        net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"), tax_category="S",
        payment_terms="Zahlbar innerhalb 14 Tagen.", notes="",
    )
    inv.customer = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                            zip_code="10115", city="Berlin", country="DE")
    inv.items = [item]
    return inv


def _text(pdf_path):
    return "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)


# ----------------------------------------------------------------------------- XML

def test_umbruch_ueberlebt_in_ram_name():
    xml = zugferd_xml.generate_xml(
        _invoice("Vertriebstraining Modul 3\n2 Tage vor Ort"), _company())
    assert "<ram:Name>Vertriebstraining Modul 3\n2 Tage vor Ort</ram:Name>" in xml


def test_sonderzeichen_werden_in_der_xml_escaped():
    xml = zugferd_xml.generate_xml(_invoice("Rabatt 5<x & mehr"), _company())
    assert "Rabatt 5&lt;x &amp; mehr" in xml


# ----------------------------------------------------------------------------- PDF

def test_pdf_erzeugung_ueberlebt_spitze_klammern(tmp_path):
    """Regression: `5<x` liess `Paragraph` mit 'unclosed tags' brechen."""
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_invoice("Mengenrabatt 5<x & <b>fett</b>"), _company(), out)
    assert out.exists()


def test_markup_in_der_beschreibung_bleibt_text(tmp_path):
    """Eine Beschreibung ist Text, kein Markup — `<b>` darf nicht fett rendern."""
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_invoice("Paket <b>Gold</b>"), _company(), out)
    assert "<b>Gold</b>" in _text(out).replace("\n", "")


def test_umbruch_wird_im_pdf_zum_zeilenumbruch(tmp_path):
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(_invoice("Erste Zeile\nZweite Zeile"), _company(), out)
    text = _text(out)
    assert "Erste Zeile" in text
    assert "Zweite Zeile" in text


# ------------------------------------------------------------------------ Anzeige

def test_detailseite_zeigt_umbrueche(pg_session):
    cust = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                    address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(cust)
    pg_session.commit()
    inv = Invoice(invoice_number=f"RE-{uuid.uuid4().hex[:8]}", customer_id=cust.id,
                  issue_date=date(2026, 6, 11), due_date=date(2026, 6, 25),
                  status="draft", currency="EUR", tax_category="S",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"))
    pg_session.add(inv)
    pg_session.flush()
    pg_session.add(InvoiceItem(
        invoice_id=inv.id, position=1, description="Zeile eins\nZeile zwei",
        unit="Stück", quantity=Decimal("1"), unit_price=Decimal("100"),
        tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
        tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00")))
    pg_session.commit()

    app.dependency_overrides[get_db] = lambda: pg_session
    html = TestClient(app, follow_redirects=False).get(f"/invoices/{inv.id}").text
    assert "pre-line" in html, (
        "Ohne white-space: pre-line kollabieren die Umbrüche — die Detailseite sähe "
        "dann anders aus als das PDF."
    )


# ------------------------------------------------------------------- Normalisierung

def test_crlf_wird_beim_speichern_normalisiert(pg_session):
    """Browser schicken \\r\\n; in der DB (und damit in der XML) soll \\n stehen."""
    cust = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                    address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(cust)
    pg_session.commit()
    cust_id = cust.id   # vor dem expunge_all() festhalten

    app.dependency_overrides[get_db] = lambda: pg_session
    r = TestClient(app, follow_redirects=False).post("/invoices/neu", data={
        "customer_id": str(cust_id),
        "issue_date": "2026-06-11",
        "due_date": "2026-06-25",
        "tax_category": "S",
        "items_json": json.dumps([{
            "description": "  Zeile eins\r\nZeile zwei  ", "unit": "Stück",
            "quantity": "1", "unit_price": "100", "tax_rate": "19"}]),
    })
    assert r.status_code == 303

    pg_session.expunge_all()
    item = (pg_session.query(InvoiceItem)
            .join(Invoice).filter(Invoice.customer_id == cust_id).first())
    assert item.description == "Zeile eins\nZeile zwei"
