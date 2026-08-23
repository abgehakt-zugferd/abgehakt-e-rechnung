"""Gemeinsame Helfer fuer Finalize-Integrationstests (#38).

Die Pipeline wird gepatcht, damit Fail-closed- und Archiv-Tests ohne Ghostscript
und Mustang deterministisch laufen. Die Testaussagen bleiben in den einzelnen
Dateien; hier nur die wiederholten Bausteine.
"""
import uuid
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem

settings = get_settings()


def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def fake_generate_pdf(invoice, comp, path):
    Path(path).write_bytes(b"%PDF-visual")


def fake_combine(pdf_path, xml_path, out_path, *a, **k):
    Path(out_path).write_bytes(b"%PDF-zugferd")
    return True


def valid_mustang():
    return {"is_valid": True,
            "raw": "Parsed PDF:valid\nSchema validation:valid\nXML:valid\nSummary: 0 errors",
            "errors": [], "warnings": []}


def cleanup(number):
    wurzel = settings.storage_path
    for p in list(wurzel.rglob("*")):
        if p.is_file() and number in p.name:
            p.unlink(missing_ok=True)
    for suffix in ("_visual.pdf", ".pdf", "_pdfa.pdf"):
        (settings.storage_path / "pdfs" / f"{number}{suffix}").unlink(missing_ok=True)
    (settings.storage_path / "xml" / f"{number}.xml").unlink(missing_ok=True)


def valid_draft(pg_session, *, prefix="RE-FC"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"{prefix}-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 7, 8), delivery_date=date(2026, 7, 8),
                  due_date=date(2026, 7, 22), currency="EUR", zugferd_profile="EN16931",
                  tax_category="S", status="draft", payment_terms="14 Tage netto",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"))
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("2"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                             tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


@contextmanager
def patched_success_pipeline(*, combine=fake_combine, validate=None):
    """Standard-Patches fuer einen erfolgreichen Finalize-Lauf."""
    mustang = validate if validate is not None else valid_mustang()
    with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
         patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
         patch("app.routers.invoices.pdfa.to_pdfa3", return_value=True), \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.combine", side_effect=combine), \
         patch("app.routers.invoices.mustang.validate", return_value=mustang):
        yield


def finalize_with_fake_pipeline(pg_session, inv_id):
    """Finalisieren mit echtem Validator-Gate, gepatchter PDF-Pipeline."""
    with patched_success_pipeline():
        return client(pg_session).post(f"/invoices/{inv_id}/finalisieren")
