"""
Finalize-End-to-End (Audit-#6): draft → prüfen → finalisieren, durch die ECHTE
ZUGFeRD-Pipeline (ReportLab → PDF/A-3 via Ghostscript → Mustang combine) gegen
echtes Postgres — KEINE Mocks. Beweist, dass eine reale Rechnung ein
rechtskonformes ZUGFeRD-PDF erzeugt (Mustang: Parsed PDF:valid XML:valid).

Die vorhandenen Finalize-Tests patchen pdf_generator/pdfa/mustang weg und prüfen
nur die Orchestrierung. Dieser Test schließt die Lücke zum tatsächlichen Artefakt.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem, ValidationResult
from app.services import mustang, pdfa

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)


def teardown_function():
    app.dependency_overrides.clear()


def _draft(pg_session, number, *, delivery_date=date(2026, 7, 8),
           menge=Decimal("2"), preis=Decimal("100.00")):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Muster Kunde GmbH",
                 address_line1="Kundenweg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(c)
    pg_session.flush()
    netto = (menge * preis).quantize(Decimal("0.01"))
    steuer = (netto * Decimal("19") / 100).quantize(Decimal("0.01"))
    inv = Invoice(invoice_number=number, customer_id=c.id, issue_date=date(2026, 7, 8),
                  delivery_date=delivery_date, due_date=date(2026, 7, 22), currency="EUR",
                  net_total=netto, tax_total=steuer,
                  gross_total=netto + steuer, tax_category="S", status="draft",
                  payment_terms="Zahlbar innerhalb 14 Tagen.")
    inv.items = [InvoiceItem(position=1, description="Beratungsleistung", unit="Std",
                             quantity=menge, unit_price=preis,
                             tax_rate=Decimal("19"), net_amount=netto,
                             tax_amount=steuer, gross_amount=netto + steuer)]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_finalize_erzeugt_gueltiges_zugferd_pdf(pg_session):
    from fastapi.testclient import TestClient
    number = f"RE-E2E-{uuid.uuid4().hex[:6]}"
    inv = _draft(pg_session, number)
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)

    # 1. Prüfen (echter Validator) → valide
    r_pruef = client.post(f"/invoices/{inv.id}/pruefen")
    assert r_pruef.status_code == 303
    pg_session.expire_all()
    vr = (pg_session.query(ValidationResult)
          .filter(ValidationResult.invoice_id == inv.id)
          .order_by(ValidationResult.validated_at.desc())
          .first())
    assert vr is not None and vr.is_valid

    pdf_path = None
    xml_path = settings.storage_path / "xml" / f"{number}.xml"
    try:
        # 2. Finalisieren → echte Pipeline
        r = client.post(f"/invoices/{inv.id}/finalisieren")
        assert r.status_code == 303

        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "issued"
        assert row.zugferd_xml and "CrossIndustryInvoice" in row.zugferd_xml
        assert row.pdf_filename == f"{number}.pdf"      # ZUGFeRD-PDF, nicht Fallback

        # 3. PDF existiert physisch
        pdf_path = settings.storage_path / "pdfs" / row.pdf_filename
        assert pdf_path.exists(), "Finalisiertes PDF fehlt auf der Platte"

        # 4. Mustang validiert das kombinierte PDF: Parsed PDF:valid XML:valid
        result = mustang.validate(pdf_path)
        assert result["is_valid"], f"ZUGFeRD-PDF ist NICHT valide:\n{result['raw']}"
        assert "Parsed PDF:valid" in result["raw"]
        assert "XML:valid" in result["raw"]
    finally:
        if pdf_path:
            pdf_path.unlink(missing_ok=True)
        (settings.storage_path / "pdfs" / f"{number}_visual.pdf").unlink(missing_ok=True)
        xml_path.unlink(missing_ok=True)


def test_kleinbetrag_ohne_leistungsdatum_wird_ein_gueltiges_zugferd_pdf(pg_session):
    """#47: der Fall, den § 33 UStDV erlaubt, muss auch am Ende ankommen.

    Das Gate lässt eine Kleinbetragsrechnung ohne Leistungsdatum seit #23/#24
    durch. Was danach kam, sah bis hierher niemand: die übrigen Finalize-Tests
    ersetzen die Pipeline durch Attrappen, und die erzeugen kein XML. Tatsächlich
    entfiel ohne Leistungsdatum der im CII-Schema zwingende Block
    <ram:ApplicableHeaderTradeDelivery>, und Mustang wies die Datei ab. Der Nutzer
    bekam eine Rechnung, die das Gesetz erlaubt, aber die Norm nicht.
    """
    from fastapi.testclient import TestClient
    number = f"RE-E2E-{uuid.uuid4().hex[:6]}"
    inv = _draft(pg_session, number, delivery_date=None,
                 menge=Decimal("1"), preis=Decimal("100.00"))
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)

    pdf_path = None
    try:
        r = client.post(f"/invoices/{inv.id}/finalisieren")
        assert r.status_code == 303, r.text

        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "issued"
        assert row.delivery_date is None          # nichts nachgetragen
        assert row.pdf_filename == f"{number}.pdf"

        pdf_path = settings.storage_path / "pdfs" / row.pdf_filename
        result = mustang.validate(pdf_path)
        assert result["is_valid"], f"ZUGFeRD-PDF ist NICHT valide:\n{result['raw'][-1500:]}"
        assert "XML:valid" in result["raw"]
    finally:
        if pdf_path:
            pdf_path.unlink(missing_ok=True)
        (settings.storage_path / "pdfs" / f"{number}_visual.pdf").unlink(missing_ok=True)
        (settings.storage_path / "xml" / f"{number}.xml").unlink(missing_ok=True)
