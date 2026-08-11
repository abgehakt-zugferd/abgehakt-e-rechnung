"""
Entwurfs-Vorschau (#142, Spec 2026-07-31).

Zentrale Leitplanke, kein Implementierungsdetail: **der Vorschau-Pfad schreibt
nichts.** `storage/pdfs/` ist das GoBD-Archiv — ein Vorschau-PDF, das dort liegt, ist
später von einem echten Beleg nicht mehr zu unterscheiden, und ein Dateiname wie
`RE-2026-004.pdf` würde beim nächsten Finalisieren überschrieben oder kollidierte mit
einem Nicht-Beleg. Also: keine Datei, kein Commit, kein Statuswechsel, kein
`ValidationResult`, keine Zuweisung an `invoice.zugferd_xml`.

Das Wasserzeichen ist ebenfalls kein Schmuck: das Vorschau-PDF trägt bereits die
endgültige Rechnungsnummer, enthält aber keine eingebettete XML. Ohne sichtbares
ENTWURF könnte ein versehentlich weitergegebenes Exemplar wie eine Rechnung wirken
(§ 14c UStG-Risiko).
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem, ValidationResult
from app.services import pdf_generator

settings = get_settings()


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _company(pg_session):
    c = pg_session.query(Company).filter(Company.id == 1).first()
    if not c:
        c = Company(id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
                    zip_code="12345", city="Musterstadt", vat_id="DE123456789",
                    tax_number="123/456/78901", bank_iban="DE00123456780000000000",
                    bank_bic="ABCDDEFF", bank_name="Testbank")
        pg_session.add(c)
        pg_session.commit()
    return c


def _invoice(pg_session, status="draft"):
    _company(pg_session)
    cust = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                    address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(cust)
    pg_session.commit()
    inv = Invoice(invoice_number=f"RE-{uuid.uuid4().hex[:8]}", customer_id=cust.id,
                  issue_date=date(2026, 6, 11), due_date=date(2026, 6, 25),
                  delivery_date=date(2026, 6, 11), status=status, currency="EUR",
                  zugferd_profile="EN16931", tax_category="S",
                  payment_terms="Zahlbar innerhalb 14 Tagen.",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"))
    pg_session.add(inv)
    pg_session.flush()
    pg_session.add(InvoiceItem(
        invoice_id=inv.id, position=1, description="Beratungsleistung", unit="Stunde",
        quantity=Decimal("1"), unit_price=Decimal("100"), tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00")))
    pg_session.commit()
    return inv


def _pdf_text(daten: bytes, tmp_path):
    ziel = tmp_path / "vorschau.pdf"
    ziel.write_bytes(daten)
    return "\n".join(p.extract_text() or "" for p in PdfReader(str(ziel)).pages)


# ---------------------------------------------------------------------- Vorschau

def test_vorschau_seite_zeigt_hinweis_und_xml(pg_session):
    inv = _invoice(pg_session)
    r = _client(pg_session).get(f"/invoices/{inv.id}/vorschau")
    assert r.status_code == 200
    assert "kein rechtsgültiges Dokument" in r.text
    assert "CrossIndustryInvoice" in r.text, "generierte XML fehlt auf der Vorschau-Seite"
    assert inv.invoice_number in r.text


def test_vorschau_pdf_liefert_pdf_bytes(pg_session):
    inv = _invoice(pg_session)
    r = _client(pg_session).get(f"/invoices/{inv.id}/vorschau.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content.startswith(b"%PDF")
    assert "inline" in r.headers.get("content-disposition", "")


def test_vorschau_pdf_traegt_das_wasserzeichen(pg_session, tmp_path):
    inv = _invoice(pg_session)
    r = _client(pg_session).get(f"/invoices/{inv.id}/vorschau.pdf")
    assert "ENTWURF" in _pdf_text(r.content, tmp_path)


def test_finalisiertes_pdf_traegt_kein_wasserzeichen(tmp_path):
    """Gegenprobe: der Default `draft=False` lässt den Finalize-Pfad unverändert."""
    cust = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                    zip_code="10115", city="Berlin", country="DE")
    inv = Invoice(invoice_number="RE-2026-777", issue_date=date(2026, 7, 8),
                  due_date=date(2026, 7, 22), net_total=Decimal("100.00"),
                  tax_total=Decimal("19.00"), gross_total=Decimal("119.00"),
                  tax_category="S", payment_terms="Zahlbar in 14 Tagen.", notes="")
    inv.customer = cust
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("1"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                             tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"))]
    comp = Company(id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
                   zip_code="12345", city="Musterstadt", vat_id="DE123456789",
                   tax_number="123/456/78901", bank_iban="DE001234567800",
                   bank_bic="ABCDDEFF", bank_name="Testbank")

    out = tmp_path / "final.pdf"
    pdf_generator.generate_pdf(inv, comp, out)
    text = "\n".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    assert "ENTWURF" not in text, (
        "Das finalisierte PDF trägt ein Wasserzeichen — der Default draft=False greift nicht."
    )


# ------------------------------------------------------------------- Leitplanken

def test_vorschau_schreibt_nichts(pg_session):
    inv = _invoice(pg_session)
    inv_id = inv.id
    pdf_dir = settings.storage_path / "pdfs"
    vorher = set(pdf_dir.glob("*")) if pdf_dir.exists() else set()

    client = _client(pg_session)
    assert client.get(f"/invoices/{inv_id}/vorschau").status_code == 200
    assert client.get(f"/invoices/{inv_id}/vorschau.pdf").status_code == 200

    nachher = set(pdf_dir.glob("*")) if pdf_dir.exists() else set()
    assert nachher == vorher, "Die Vorschau hat ins GoBD-Archiv geschrieben"

    pg_session.expunge_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == inv_id).first()
    assert frisch.status == "draft"
    assert frisch.zugferd_xml is None, "Vorschau hat zugferd_xml gesetzt"
    assert frisch.pdf_filename is None
    assert pg_session.query(ValidationResult).filter(
        ValidationResult.invoice_id == inv_id).count() == 0, "Vorschau hat protokolliert"


def test_beide_routen_sind_400_fuer_finalisierte_rechnungen(pg_session):
    inv = _invoice(pg_session, status="issued")
    client = _client(pg_session)
    assert client.get(f"/invoices/{inv.id}/vorschau").status_code == 400
    assert client.get(f"/invoices/{inv.id}/vorschau.pdf").status_code == 400


def test_vorschau_unbekannte_rechnung_ist_404(pg_session):
    client = _client(pg_session)
    assert client.get(f"/invoices/{uuid.uuid4()}/vorschau").status_code == 404
    assert client.get(f"/invoices/{uuid.uuid4()}/vorschau.pdf").status_code == 404
