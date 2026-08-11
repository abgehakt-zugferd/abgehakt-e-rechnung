"""
GET /invoices/{id}/pdf (Audit-#7): Bisher 0 Tests. Der Handler liefert 404, wenn
die Rechnung fehlt, kein pdf_filename hat ODER die Datei nicht auf der Platte liegt;
sonst 200 mit application/pdf.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice

settings = get_settings()


def teardown_function():
    app.dependency_overrides.clear()


def _invoice(pg_session, pdf_filename):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("0"), tax_total=Decimal("0"), gross_total=Decimal("0"),
                  status="issued", pdf_filename=pdf_filename)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def test_pdf_200_when_file_exists(pg_session):
    name = f"pdftest-{uuid.uuid4().hex[:8]}.pdf"
    path = settings.storage_path / "pdfs" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n%mini\n")
    try:
        inv = _invoice(pg_session, name)
        r = _client(pg_session).get(f"/invoices/{inv.id}/pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
    finally:
        path.unlink(missing_ok=True)


def test_pdf_404_when_file_missing_on_disk(pg_session):
    inv = _invoice(pg_session, f"nicht-da-{uuid.uuid4().hex[:8]}.pdf")
    r = _client(pg_session).get(f"/invoices/{inv.id}/pdf")
    assert r.status_code == 404


def test_pdf_404_when_no_pdf_filename(pg_session):
    inv = _invoice(pg_session, None)
    r = _client(pg_session).get(f"/invoices/{inv.id}/pdf")
    assert r.status_code == 404


def test_pdf_404_unknown_invoice(pg_session):
    r = _client(pg_session).get(f"/invoices/{uuid.uuid4()}/pdf")
    assert r.status_code == 404
