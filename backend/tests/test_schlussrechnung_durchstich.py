"""Schlussrechnung, Durchstich (#259): Formular-POST bis XML und PDF.

Eine Rechnung (380) verrechnet gestellte, bezahlte Anzahlungen: BT-112 voll,
BT-113 Summe der Brutto der Anzahlungen, BT-115 der Rest, BG-3 je Anzahlung eine
vorausgegangene Rechnung, im PDF je Anzahlung eine Abzugszeile. Durch die echte
ZUGFeRD-Pipeline; Mustang liest das Ergebnis als gueltig.
"""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.invoice import Invoice
from app.services import mustang, pdfa
from tests.helpers import mustang_befund, pdf
from tests.helpers.schlussrechnung import anzahlung, kunde, schluss_ueber_formular

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _aufraeumen(nummer):
    for pfad in (settings.storage_path / "pdfs" / f"{nummer}.pdf",
                 settings.storage_path / "pdfs" / f"{nummer}_visual.pdf",
                 settings.storage_path / "xml" / f"{nummer}.xml"):
        pfad.unlink(missing_ok=True)


def _stellen(pg_session, client, entwurf):
    r = client.post(f"/invoices/{entwurf.id}/finalisieren")
    assert r.status_code == 303, r.text
    pg_session.expire_all()
    return pg_session.get(Invoice, entwurf.id)


def test_schlussrechnung_mit_steuer_traegt_anzahlung_in_xml_und_pdf(pg_session):
    k = kunde(pg_session)
    az = anzahlung(pg_session, k)  # 100,00 netto, 19,00 Steuer, 119,00 brutto
    client = _client(pg_session)
    entwurf = schluss_ueber_formular(pg_session, client, k, [az])
    try:
        beleg = _stellen(pg_session, client, entwurf)
        xml = beleg.zugferd_xml
        assert "<ram:TypeCode>380</ram:TypeCode>" in xml
        assert "<ram:GrandTotalAmount>238.00</ram:GrandTotalAmount>" in xml
        assert "<ram:TotalPrepaidAmount>119.00</ram:TotalPrepaidAmount>" in xml
        assert "<ram:DuePayableAmount>119.00</ram:DuePayableAmount>" in xml
        assert xml.count("<ram:InvoiceReferencedDocument>") == 1
        assert f"<ram:IssuerAssignedID>{az.invoice_number}</ram:IssuerAssignedID>" in xml
        assert '<qdt:DateTimeString format="102">20260708</qdt:DateTimeString>' in xml

        pdf_pfad = settings.storage_path / "pdfs" / beleg.pdf_filename
        mustang_befund.gueltig(mustang.validate(pdf_pfad))
        text = pdf.text(pdf_pfad)
        assert f"abzüglich Anzahlung, Rechnung {az.invoice_number} vom 08.07.2026" in text
        assert "Netto 100,00 €" in text and "MwSt. 19,00 €" in text
    finally:
        _aufraeumen(entwurf.invoice_number)
