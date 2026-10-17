"""Finalize-End-to-End einer Honorargutschrift (Spec #156, Kriterium 8).

Voller Weg gegen die echte Datenbank und die ECHTE Pipeline (ReportLab,
Ghostscript, Mustang): angenommener Auftrag → Entwurf → prüfen → finalisieren
→ Archiv. Mustang ist die Wahrheit: gefordert sind is_valid UND XML:valid,
genau wie im Finalisieren (routers/invoices.py); XML:valid allein genügt
nicht. Scheitert eine Stufe, liegt am Ende kein Beleg im Archiv.

Übersprungene Tests gelten hier als Fehlschlag; fehlt Mustang, ist der Lauf
rot (deshalb kein stiller Skip im Container-Lauf von run-tests.sh).
"""
import uuid

import pytest

from app.config import get_settings
from app.models.customer import Customer
from app.models.invoice import Invoice, ValidationResult
from app.services import mustang, pdfa
from app.services.abrechnungsauftrag_wirkung import entwuerfe_anlegen
from tests.test_abrechnungsauftrag_wirkung import _kunde, _urteil

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)


def _archiv_hat_nichts(number):
    wurzel = settings.storage_path
    return [str(p) for p in wurzel.rglob("*") if p.is_file() and number in p.name]


def test_389_vom_auftrag_bis_zum_archiv_durch_die_echte_pipeline(pg_session):
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.main import app

    _kunde(pg_session, uuid.UUID("3f5b1c80-0000-4000-8000-00000000000a"))
    entwurf = entwuerfe_anlegen(pg_session, _urteil(), dateiname="auftrag.json")[0]
    pg_session.commit()
    nummer = entwurf.invoice_number
    pdf_path = None
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    try:
        # 1. Prüfen: echter Validator, echtes Mustang auf der erzeugten XML.
        r_pruef = client.post(f"/invoices/{entwurf.id}/pruefen")
        assert r_pruef.status_code == 303, r_pruef.text
        pg_session.expire_all()
        vr = (pg_session.query(ValidationResult)
              .filter(ValidationResult.invoice_id == entwurf.id)
              .order_by(ValidationResult.validated_at.desc())
              .first())
        assert vr is not None and vr.is_valid, vr.mustang_output if vr else None

        # 2. Finalisieren: echte Pipeline, kein Attrappen-Mustang.
        r = client.post(f"/invoices/{entwurf.id}/finalisieren")
        assert r.status_code == 303, r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, entwurf.id)
        assert row.status == "issued"
        assert row.zugferd_xml and "<ram:TypeCode>389</ram:TypeCode>" in row.zugferd_xml
        assert row.pdf_filename == f"{nummer}.pdf"

        # 3. Beleg liegt physisch im Archiv.
        pdf_path = settings.storage_path / "pdfs" / row.pdf_filename
        assert pdf_path.exists(), "Finalisiertes PDF fehlt auf der Platte"

        # 4. Mustang nimmt die 389 mit getauschten Rollen an: UND-Bedingung.
        result = mustang.validate(pdf_path)
        assert result["is_valid"], (
            f"Mustang lehnt die 389 ab:\nFehler: {result['errors']}\n"
            f"Rohbericht:\n{result['raw']}\nXML:\n{row.zugferd_xml}"
        )
        assert "XML:valid" in result["raw"], result["raw"]
        assert "Parsed PDF:valid" in result["raw"]
    finally:
        if pdf_path:
            pdf_path.unlink(missing_ok=True)
        (settings.storage_path / "pdfs" / f"{nummer}_visual.pdf").unlink(missing_ok=True)
        (settings.storage_path / "xml" / f"{nummer}.xml").unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_scheitert_eine_stufe_liegt_nichts_im_archiv(pg_session):
    """Stufe Validator: fehlt dem Verkäufer (BG-4) jede Steuerkennung, sperrt
    der gezielte Befund das Finalisieren; der Beleg bleibt draft, und im
    Archiv liegt keine Datei mit der Nummer. Der Entwurf entsteht trotzdem:
    die Steuer wird beim Anlegen aus dem Status abgeleitet, nicht aus der
    Kennung (die ist erst für den Beleg Pflicht, § 14 Abs. 4 S. 1 Nr. 2 UStG)."""
    from fastapi.testclient import TestClient
    from app.database import get_db
    from app.main import app

    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autorin Ohne Kennung",
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
        gutschriftempfaenger=True, ust_status="regelbesteuert",
        tax_number=None, vat_id=None,
    )
    pg_session.add(kunde)
    pg_session.flush()
    urteil = _urteil()
    gutschrift = urteil.nutzlast["gutschriften"][0]
    gutschrift["beteiligter"]["partner_id"] = str(kunde.id)
    entwurf = entwuerfe_anlegen(pg_session, urteil)[0]
    pg_session.commit()
    nummer = entwurf.invoice_number
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    try:
        assert entwurf.status == "draft"
        r = client.post(f"/invoices/{entwurf.id}/finalisieren")
        assert r.status_code == 400
        # Die HTTP-Fehlerseite zeigt den Befundtext, nicht den internen Code.
        # Beide gehören zum selben Befund; Status und Archiv bleiben geprüft.
        from app.models.company import Company
        from app.services.validator import validate_invoice
        errors, _ = validate_invoice(
            entwurf, pg_session.query(Company).filter(Company.id == 1).one())
        befund = next(e for e in errors
                      if e.code == "SELF_BILLING_SELLER_TAX_ID_MISSING")
        assert befund.message in r.text
        pg_session.expire_all()
        assert pg_session.get(Invoice, entwurf.id).status == "draft"
        assert _archiv_hat_nichts(nummer) == []
    finally:
        (settings.storage_path / "pdfs" / f"{nummer}_visual.pdf").unlink(missing_ok=True)
        (settings.storage_path / "xml" / f"{nummer}.xml").unlink(missing_ok=True)
        app.dependency_overrides.clear()


def test_389_finalisieren_stornieren_storno_finalisieren(client, pg_session):
    from xml.etree import ElementTree as ET
    from app.services.belegart import belegart
    from tests.test_validator_389 import _kunde, _entwurf
    from tests.helpers.finalize_pipeline import cleanup

    original = _entwurf(pg_session, _kunde(pg_session))
    nummern = [original.invoice_number]
    try:
        result = client.post(f'/invoices/{original.id}/finalisieren')
        assert result.status_code == 303, result.text
        result = client.post(f'/invoices/{original.id}/storno')
        assert result.status_code == 303, result.text
        pg_session.expire_all()
        storno = pg_session.query(Invoice).filter(Invoice.original_invoice_id == original.id).one()
        nummern.append(storno.invoice_number)
        assert storno.invoice_type == 'self_billing_storno'
        result = client.post(f'/invoices/{storno.id}/finalisieren')
        assert result.status_code == 303, result.text
        pg_session.refresh(storno)
        assert storno.status == 'issued'
        ns = {'ram': 'urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100'}
        xml = ET.fromstring(storno.zugferd_xml)
        assert xml.find('.//ram:TypeCode', ns).text == belegart(storno.invoice_type).bt3
        assert xml.find('.//ram:InvoiceReferencedDocument/ram:IssuerAssignedID', ns).text == original.invoice_number
        assert xml.find('.//ram:SellerTradeParty/ram:Name', ns).text == original.customer.name
        report = mustang.validate(settings.storage_path / 'pdfs' / storno.pdf_filename)
        assert report['is_valid'], f"{report['errors']}\n{report['raw']}"
        assert 'XML:valid' in report['raw'], report['raw']
    finally:
        for nummer in nummern:
            cleanup(nummer)
