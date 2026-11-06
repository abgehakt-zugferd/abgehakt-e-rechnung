"""Schlussrechnung (#259, Teil 1): Abzugszeile im PDF, Belegsprache und Steuerausweis.

Naht: Formular-POST und Finalisieren durch die echte Pipeline, gelesen wird der
Text des erzeugten PDFs.
"""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.invoice import Invoice
from app.services import mustang, pdfa
from tests.helpers import pdf
from tests.helpers.schlussrechnung import anzahlung, kunde, schluss_ueber_formular

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)


def teardown_function():
    app.dependency_overrides.clear()


def _pdf_text(pg_session, az_kw, **form_kw):
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    k = kunde(pg_session)
    az = anzahlung(pg_session, k, **az_kw)
    entwurf = schluss_ueber_formular(pg_session, client, k, [az], **form_kw)
    nummer = entwurf.invoice_number
    try:
        r = client.post(f"/invoices/{entwurf.id}/finalisieren")
        assert r.status_code == 303, r.text
        pg_session.expire_all()
        beleg = pg_session.get(Invoice, entwurf.id)
        return az, pdf.text(settings.storage_path / "pdfs" / beleg.pdf_filename)
    finally:
        for pfad in (settings.storage_path / "pdfs" / f"{nummer}.pdf",
                     settings.storage_path / "pdfs" / f"{nummer}_visual.pdf",
                     settings.storage_path / "xml" / f"{nummer}.xml"):
            pfad.unlink(missing_ok=True)


def test_englischer_beleg_nennt_die_anzahlung_englisch(pg_session):
    az, text = _pdf_text(pg_session, {}, extra={"document_language": "en"})
    assert f"less advance payment, invoice {az.invoice_number} dated 2026-07-08" in text
    assert "abzüglich" not in text


def test_anzahlung_ohne_steuer_zeigt_weder_netto_noch_steuerzeile(pg_session):
    az, text = _pdf_text(pg_session, {"satz": "0"})
    assert f"abzüglich Anzahlung, Rechnung {az.invoice_number} vom 08.07.2026" in text
    assert "Netto 100,00 €" not in text
