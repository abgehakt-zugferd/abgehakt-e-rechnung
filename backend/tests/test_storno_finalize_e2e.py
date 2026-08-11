"""
Storno-End-to-End (#98 P0.3, schließt ROADMAP #5 / Issue #11): issued Original →
Storno → prüfen → finalisieren, durch die ECHTE ZUGFeRD-Pipeline. Beweist, dass
eine Gutschrift ein rechtskonformes ZUGFeRD-PDF mit UN-CEFACT TypeCode 381 erzeugt
(Mustang: Parsed PDF:valid XML:valid). Der bisherige test_storno_integration.py
stoppte bei der credit_note im Status 'draft'.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, pdfa

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)


def teardown_function():
    app.dependency_overrides.clear()


def _draft_original(pg_session):
    """Echter Entwurf — wird im Test durch die ECHTE Finalize-Pipeline zu issued
    (nicht ORM-`status=issued` geseedet). So beweist der E2E die Kette
    finalize(original) → storno → finalize(storno), nicht ein synthetisches Original."""
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Muster Kunde GmbH",
                 address_line1="Kundenweg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"ALT-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 7, 8), delivery_date=date(2026, 7, 8),
                  due_date=date(2026, 7, 22), currency="EUR", zugferd_profile="EN16931",
                  tax_category="S", status="draft", payment_terms="Zahlbar in 14 Tagen.",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"))
    inv.items = [InvoiceItem(position=1, description="Beratungsleistung", unit="Std",
                             quantity=Decimal("2"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                             tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_storno_finalize_erzeugt_gueltige_gutschrift(pg_session):
    original = _draft_original(pg_session)
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)

    # 0. Original ECHT finalisieren (Fail-closed-Pipeline → issued + ZUGFeRD-PDF)
    r = client.post(f"/invoices/{original.id}/finalisieren")
    assert r.status_code == 303, r.text
    pg_session.expire_all()
    original = pg_session.get(Invoice, original.id)
    assert original.status == "issued"
    assert original.pdf_filename == f"{original.invoice_number}.pdf"
    original_number = original.invoice_number
    original_pdf = settings.storage_path / "pdfs" / original.pdf_filename
    original_xml = settings.storage_path / "xml" / f"{original_number}.xml"
    assert original_pdf.exists()   # echtes finalisiertes Artefakt, kein Fake-Seed

    # 1. Storno erzeugen (credit_note, draft)
    r = client.post(f"/invoices/{original.id}/storno")
    assert r.status_code == 303
    pg_session.expire_all()
    storno = (pg_session.query(Invoice)
              .filter(Invoice.original_invoice_id == original.id).first())
    assert storno is not None

    pdf_path = None
    xml_path = settings.storage_path / "xml" / f"{storno.invoice_number}.xml"
    try:
        # 2. Prüfen (echter Validator) + 3. Finalisieren (echte Pipeline)
        client.post(f"/invoices/{storno.id}/pruefen")
        r = client.post(f"/invoices/{storno.id}/finalisieren")
        assert r.status_code == 303, r.text

        pg_session.expire_all()
        row = pg_session.get(Invoice, storno.id)
        assert row.status == "issued"
        assert row.invoice_type == "credit_note"
        # TypeCode 381 (Gutschrift/Storno) in der rechtlich maßgeblichen XML
        assert "<ram:TypeCode>381</ram:TypeCode>" in row.zugferd_xml
        # BT-25: die Gutschrift MUSS die Original-Rechnung referenzieren — ohne
        # InvoiceReferencedDocument ist die 381 fachlich kaputt (Schema kann grün sein).
        assert "<ram:InvoiceReferencedDocument>" in row.zugferd_xml
        assert original_number in row.zugferd_xml
        assert row.pdf_filename == f"{storno.invoice_number}.pdf"  # ZUGFeRD-PDF, kein Fallback

        pdf_path = settings.storage_path / "pdfs" / row.pdf_filename
        assert pdf_path.exists()

        # 4. Mustang validiert das kombinierte PDF
        result = mustang.validate(pdf_path)
        assert result["is_valid"], f"Storno-ZUGFeRD-PDF NICHT valide:\n{result['raw']}"
        assert "Parsed PDF:valid" in result["raw"]
        assert "XML:valid" in result["raw"]

        # Original bleibt unverändert issued
        original_row = pg_session.get(Invoice, original.id)
        assert original_row.status == "issued"
    finally:
        if pdf_path:
            pdf_path.unlink(missing_ok=True)
        (settings.storage_path / "pdfs" / f"{storno.invoice_number}_visual.pdf").unlink(missing_ok=True)
        xml_path.unlink(missing_ok=True)
        original_pdf.unlink(missing_ok=True)
        original_xml.unlink(missing_ok=True)
        (settings.storage_path / "pdfs" / f"{original_number}_visual.pdf").unlink(missing_ok=True)
