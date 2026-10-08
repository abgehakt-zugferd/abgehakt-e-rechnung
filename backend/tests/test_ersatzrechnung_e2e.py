"""
Ersatzrechnung End-to-End (docs/specs/ersatzrechnung.md): gestelltes Original →
gestellte Gutschrift → Ersatzrechnung ueber POST /invoices/neu → finalisieren,
durch die ECHTE ZUGFeRD-Pipeline. Beweist, dass die Ersatzrechnung eine
gewoehnliche Rechnung (380) bleibt und im XML per BT-25/BT-26 auf die ersetzte
Rechnung verweist, und dass Mustang den Beleg als gueltig liest.
"""
import json
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


def _kunde(pg_session, name):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
                 address_line1="Kundenweg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(c)
    pg_session.flush()
    return c


def _original_entwurf(pg_session, kunde):
    inv = Invoice(invoice_number=f"ALT-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=date(2026, 7, 8), delivery_date=date(2026, 7, 8),
                  due_date=date(2026, 7, 22), currency="EUR", zugferd_profile="EN16931",
                  tax_category="S", status="draft", payment_terms="Zahlbar in 14 Tagen.",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"))
    inv.items = [InvoiceItem(position=1, description="Beratungsleistung", unit="Stunde",
                             quantity=Decimal("2"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                             tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _artefakte(nummer):
    return [settings.storage_path / "pdfs" / f"{nummer}.pdf",
            settings.storage_path / "pdfs" / f"{nummer}_visual.pdf",
            settings.storage_path / "xml" / f"{nummer}.xml"]


def test_ersatzrechnung_verweist_im_xml_auf_die_stornierte_rechnung(pg_session):
    falsch = _kunde(pg_session, "Falsche Probe GmbH")
    richtig = _kunde(pg_session, "Richtige Probe GmbH")
    original = _original_entwurf(pg_session, falsch)
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    nummern = []
    try:
        r = client.post(f"/invoices/{original.id}/finalisieren")
        assert r.status_code == 303, r.text
        nummern.append(original.invoice_number)

        r = client.post(f"/invoices/{original.id}/storno")
        assert r.status_code == 303, r.text
        pg_session.expire_all()
        gutschrift = (pg_session.query(Invoice)
                      .filter(Invoice.original_invoice_id == original.id).one())
        nummern.append(gutschrift.invoice_number)
        r = client.post(f"/invoices/{gutschrift.id}/finalisieren")
        assert r.status_code == 303, r.text

        r = client.post("/invoices/neu", data={
            "customer_id": str(richtig.id),
            "issue_date": "2026-07-10",
            "due_date": "2026-07-24",
            "delivery_date": "2026-07-08",
            "tax_category": "S",
            "payment_terms": "Zahlbar in 14 Tagen.",
            "ersetzt_invoice_id": str(original.id),
            "items_json": json.dumps([
                {"description": "Beratungsleistung", "unit": "Stunde", "quantity": "2",
                 "unit_price": "100", "tax_rate": "19"},
            ]),
        })
        assert r.status_code == 303, r.text
        pg_session.expire_all()
        ersatz = (pg_session.query(Invoice)
                  .filter(Invoice.customer_id == richtig.id).one())
        nummern.append(ersatz.invoice_number)

        r = client.post(f"/invoices/{ersatz.id}/finalisieren")
        assert r.status_code == 303, r.text

        pg_session.expire_all()
        row = pg_session.get(Invoice, ersatz.id)
        assert row.status == "issued"
        assert "<ram:TypeCode>380</ram:TypeCode>" in row.zugferd_xml
        referenz = row.zugferd_xml.split("<ram:InvoiceReferencedDocument>", 1)
        assert len(referenz) == 2, "BT-25 fehlt in der Ersatzrechnung"
        assert f"<ram:IssuerAssignedID>{original.invoice_number}</ram:IssuerAssignedID>" in referenz[1]
        assert '<qdt:DateTimeString format="102">20260708</qdt:DateTimeString>' in referenz[1]

        result = mustang.validate(settings.storage_path / "pdfs" / row.pdf_filename)
        assert result["is_valid"], f"Ersatzrechnung NICHT valide:\n{result['raw']}"
    finally:
        for nummer in nummern:
            for pfad in _artefakte(nummer):
                pfad.unlink(missing_ok=True)
