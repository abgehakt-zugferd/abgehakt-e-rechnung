"""Bestellnummer des Kunden als eigenes Feld (BT-13, #101).

buyer_reference bleibt BT-10 (Leitweg-ID / sonstige Käuferreferenz). Die
Bestellnummer / Purchase Order steht daneben als buyer_order_reference und
wird als ram:BuyerOrderReferencedDocument ausgegeben. Ohne sie entsteht kein
leeres Element.
"""
import os
import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, pdf_generator, zugferd_xml
from app.services.invoice_guard import InvoiceStateError
from app.services.storno import build_storno


def _company(**over):
    from app.models.company import Company
    kw = dict(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", country="DE",
        email="info@example.de", phone="+49 111 222333",
        contact_name="Maria Muster",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE33PROBE0000000000001", bank_bic="ABCDDEFF",
        bank_name="Testbank",
    )
    kw.update(over)
    return Company(**kw)


def _customer(**over) -> Customer:
    kw = dict(
        customer_number="K-1", name="Kunde GmbH", address_line1="Kundenweg 2",
        zip_code="80331", city="München", country="DE",
        email="rechnung@kunde.example",
    )
    kw.update(over)
    return Customer(**kw)


def _invoice(customer=None, **over) -> Invoice:
    item = InvoiceItem(
        position=1, description="Beratungsleistung", quantity=Decimal("2"),
        unit="Std", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"),
        gross_amount=Decimal("238.00"),
    )
    kw = dict(
        invoice_number="RE-2026-778", issue_date=date(2026, 8, 9),
        delivery_date=date(2026, 8, 9), due_date=date(2026, 8, 23), currency="EUR",
        net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"), tax_category="S",
        buyer_reference="LW-991",
        buyer_order_reference="PO-445",
        payment_terms="Zahlbar innerhalb 14 Tagen.", notes="",
    )
    kw.update(over)
    inv = Invoice(**kw)
    inv.customer = customer if customer is not None else _customer()
    inv.items = [item]
    return inv


def _seed_kunde(pg_session) -> Customer:
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
        address_line1="Weg 1", zip_code="80331", city="München",
        country="DE", email="rechnung@kunde.example",
    )
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def test_das_rechnungsformular_hat_ein_feld_fuer_die_bestellnummer(pg_session):
    _seed_kunde(pg_session)
    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        html = TestClient(app, follow_redirects=False).get("/invoices/neu").text
    finally:
        app.dependency_overrides.clear()

    assert 'name="buyer_order_reference"' in html
    assert "Bestellnummer" in html


def test_die_bestellnummer_ueberlebt_das_anlegen_und_das_bearbeiten(pg_session):
    kunde = _seed_kunde(pg_session)
    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        client = TestClient(app, follow_redirects=False)
        felder = {
            "customer_id": str(kunde.id),
            "issue_date": "2026-08-09",
            "due_date": "2026-08-23",
            "tax_category": "S",
            "buyer_reference": "LW-991",
            "buyer_order_reference": "PO-445",
            "items_json": (
                '[{"description":"Leistung","quantity":"1","unit":"Stück",'
                '"unit_price":"100.00","tax_rate":"19"}]'
            ),
        }
        antwort = client.post("/invoices/neu", data=felder)
        assert antwort.status_code == 303, antwort.text
        rechnung_id = antwort.headers["location"].rsplit("/", 1)[-1]

        gespeichert = pg_session.query(Invoice).filter(
            Invoice.id == uuid.UUID(rechnung_id)
        ).first()
        pg_session.refresh(gespeichert)
        assert gespeichert.buyer_order_reference == "PO-445"
        assert gespeichert.buyer_reference == "LW-991"

        geaendert = client.post(
            f"/invoices/{rechnung_id}/bearbeiten",
            data={**felder, "buyer_order_reference": "PO-9999"},
        )
        assert geaendert.status_code == 303, geaendert.text
        pg_session.refresh(gespeichert)
        assert gespeichert.buyer_order_reference == "PO-9999"
    finally:
        app.dependency_overrides.clear()


def test_die_bestellnummer_steht_auf_dem_pdf(tmp_path):
    from pypdf import PdfReader

    ziel = tmp_path / "rechnung.pdf"
    pdf_generator.generate_pdf(_invoice(), _company(), ziel)
    text = "\n".join(seite.extract_text() or "" for seite in PdfReader(str(ziel)).pages)

    assert "PO-445" in text, text
    assert "Bestellnummer" in text, text


def test_die_bestellnummer_steht_auf_der_detailseite(pg_session):
    kunde = _seed_kunde(pg_session)
    rechnung = _invoice(customer=kunde)
    rechnung.invoice_number = f"RE-2026-{uuid.uuid4().hex[:6]}"
    pg_session.add(rechnung)
    pg_session.commit()

    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        html = TestClient(app).get(f"/invoices/{rechnung.id}").text
    finally:
        app.dependency_overrides.clear()

    assert "PO-445" in html
    assert "Bestellnummer" in html


def test_storno_uebernimmt_bestellnummer():
    """Der Empfaenger gleicht auch die Gutschrift gegen dieselbe Bestellung ab."""
    original = _invoice()
    original.id = uuid.uuid4()
    original.customer_id = uuid.uuid4()
    storno = build_storno(original, "RE-2026-002", date(2026, 9, 1))
    assert storno.buyer_order_reference == "PO-445"


def test_bestellnummer_unveraenderlich_nach_finalisierung(pg_session):
    kunde = _seed_kunde(pg_session)
    rechnung = _invoice(customer=kunde, buyer_order_reference="PO-445")
    rechnung.invoice_number = f"RE-2026-{uuid.uuid4().hex[:6]}"
    rechnung.status = "issued"
    pg_session.add(rechnung)
    pg_session.commit()

    rechnung.buyer_order_reference = "PO-HACK"
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


@pytest.mark.skipif(not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_rechnung_mit_bestellnummer_bleibt_schema_gueltig():
    """Mustang sieht die Bestellnummer wirklich: ohne sie waere der Lauf wertlos."""
    inv = _invoice(buyer_order_reference="PO-445", buyer_reference="LW-991")
    xml = zugferd_xml.generate_xml(inv, _company())
    assert "BuyerOrderReferencedDocument" in xml
    assert "PO-445" in xml

    fd, name = tempfile.mkstemp(suffix=".xml")
    p = Path(name)
    try:
        os.write(fd, xml.encode("utf-8"))
        os.close(fd)
        ergebnis = mustang.validate(p)
    finally:
        p.unlink(missing_ok=True)

    assert ergebnis["is_valid"], ergebnis.get("raw", "")
