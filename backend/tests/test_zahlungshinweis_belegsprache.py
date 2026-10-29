"""#248: Zahlungshinweis folgt der Belegsprache beim Speichern.

Naht: POST Anlegen und Bearbeiten ueber den Test-Client.
Wenn das Feld (getrimmt) genau die Firmenvorgabe der anderen Sprache traegt,
wird die Vorgabe der gewaehlten Sprache gespeichert. Freitext bleibt.
"""
from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator, zugferd_xml

VORGABE_DE = "Zahlbar innerhalb von 14 Tagen ohne Abzug."
VORGABE_EN = "Payable within 14 days of receipt without deduction."
FREITEXT = "Sondervereinbarung Probe bleibt stehen."

NS = {
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
}


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde(pg_session):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Kunde GmbH",
        address_line1="Weg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
        vat_id="DE987654321",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _firma_mit_vorgaben(pg_session, *, en=VORGABE_EN, de=VORGABE_DE):
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    firma.payment_terms_default = de
    firma.payment_terms_default_en = en
    pg_session.commit()
    return firma


def _payload(kunde, *, document_language="en", payment_terms="", **extra):
    daten = {
        "customer_id": str(kunde.id),
        "issue_date": "2026-10-09",
        "due_date": "2026-10-23",
        "delivery_date": "2026-10-09",
        "tax_category": "S",
        "document_language": document_language,
        "payment_terms": payment_terms,
        "items_json": json.dumps([{
            "description": "Beratung Probe",
            "unit": "Stunde",
            "quantity": "1",
            "unit_price": "100",
            "tax_rate": "19",
        }]),
    }
    daten.update(extra)
    return daten


def _entwurf(pg_session, kunde, *, document_language="de", payment_terms=VORGABE_DE):
    item = InvoiceItem(
        position=1,
        description="Beratung Probe",
        unit="Stunde",
        quantity=Decimal("1"),
        unit_price=Decimal("100.00"),
        tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"),
        tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"),
    )
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:8]}",
        customer_id=kunde.id,
        issue_date=date(2026, 10, 9),
        due_date=date(2026, 10, 23),
        delivery_date=date(2026, 10, 9),
        payment_terms=payment_terms,
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        document_language=document_language,
        status="draft",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
    )
    inv.items = [item]
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    inv.customer = kunde
    return inv


def _pdf_text(inv, company, tmp_path):
    out = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, company, out)
    return "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)


def _bt20(inv, company):
    root = ET.fromstring(zugferd_xml.generate_xml(inv, company))
    el = root.find(".//ram:SpecifiedTradePaymentTerms/ram:Description", NS)
    return el.text if el is not None else None


def test_anlegen_ersetzt_deutsche_vorgabe_bei_englischer_belegsprache(pg_session, tmp_path):
    kunde = _kunde(pg_session)
    firma = _firma_mit_vorgaben(pg_session)
    client = _client(pg_session)

    r = client.post(
        "/invoices/neu",
        data=_payload(kunde, document_language="en", payment_terms=VORGABE_DE),
    )
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.get(Invoice, uuid.UUID(r.headers["location"].rsplit("/", 1)[-1]))
    assert inv.document_language == "en"
    assert inv.payment_terms == VORGABE_EN

    text = _pdf_text(inv, firma, tmp_path)
    assert VORGABE_EN in text
    assert VORGABE_DE not in text
    assert _bt20(inv, firma) == VORGABE_EN


def test_bearbeiten_ersetzt_deutsche_vorgabe_bei_sprachwechsel_nach_en(pg_session, tmp_path):
    kunde = _kunde(pg_session)
    firma = _firma_mit_vorgaben(pg_session)
    draft = _entwurf(pg_session, kunde, document_language="de", payment_terms=VORGABE_DE)
    client = _client(pg_session)

    r = client.post(
        f"/invoices/{draft.id}/bearbeiten",
        data=_payload(
            kunde,
            document_language="en",
            payment_terms=VORGABE_DE,
            issue_date=draft.issue_date.isoformat(),
            due_date=draft.due_date.isoformat(),
        ),
    )
    assert r.status_code in (303, 200)
    pg_session.expire_all()
    draft = pg_session.get(Invoice, draft.id)
    assert draft.document_language == "en"
    assert draft.payment_terms == VORGABE_EN

    text = _pdf_text(draft, firma, tmp_path)
    assert VORGABE_EN in text
    assert _bt20(draft, firma) == VORGABE_EN


def test_anlegen_ersetzt_englische_vorgabe_bei_deutscher_belegsprache(pg_session):
    kunde = _kunde(pg_session)
    _firma_mit_vorgaben(pg_session)
    client = _client(pg_session)

    r = client.post(
        "/invoices/neu",
        data=_payload(kunde, document_language="de", payment_terms=f"  {VORGABE_EN}  "),
    )
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.get(Invoice, uuid.UUID(r.headers["location"].rsplit("/", 1)[-1]))
    assert inv.document_language == "de"
    assert inv.payment_terms == VORGABE_DE


def test_freitext_bleibt_beim_sprachwechsel(pg_session):
    kunde = _kunde(pg_session)
    _firma_mit_vorgaben(pg_session)
    draft = _entwurf(pg_session, kunde, payment_terms=FREITEXT)
    client = _client(pg_session)

    r = client.post(
        f"/invoices/{draft.id}/bearbeiten",
        data=_payload(
            kunde,
            document_language="en",
            payment_terms=FREITEXT,
            issue_date=draft.issue_date.isoformat(),
            due_date=draft.due_date.isoformat(),
        ),
    )
    assert r.status_code in (303, 200)
    pg_session.expire_all()
    draft = pg_session.get(Invoice, draft.id)
    assert draft.document_language == "en"
    assert draft.payment_terms == FREITEXT


def test_englisch_ohne_vorgabe_bei_deutscher_vorgabe_im_feld_ist_400(pg_session):
    kunde = _kunde(pg_session)
    _firma_mit_vorgaben(pg_session, en="")
    client = _client(pg_session)
    vorher = pg_session.query(Invoice).count()

    r = client.post(
        "/invoices/neu",
        data=_payload(kunde, document_language="en", payment_terms=VORGABE_DE),
    )
    assert r.status_code == 400
    pg_session.expire_all()
    assert pg_session.query(Invoice).count() == vorher


def test_gestellter_beleg_behaelt_deutschen_hinweis_im_englischen_pdf(pg_session, tmp_path):
    """Gestellte Belege: gespeicherter Text bleibt, Rendern tauscht nicht."""
    kunde = _kunde(pg_session)
    firma = _firma_mit_vorgaben(pg_session)
    inv = _entwurf(pg_session, kunde, document_language="en", payment_terms=VORGABE_DE)
    inv.status = "issued"
    pg_session.commit()
    pg_session.refresh(inv)
    inv.customer = kunde

    text = _pdf_text(inv, firma, tmp_path)
    assert VORGABE_DE in text
    assert VORGABE_EN not in text
    assert _bt20(inv, firma) == VORGABE_DE


def test_formular_js_ersetzt_vorgabe_der_anderen_sprache(pg_session):
    """Kein JS-Runner im Repo: Zusicherung an der gerenderten Formular-Ausgabe."""
    _firma_mit_vorgaben(pg_session)
    client = _client(pg_session)
    r = client.get("/invoices/neu")
    assert r.status_code == 200
    html = r.text
    assert "onDocumentLanguageChange" in html
    # #248: nicht nur leeres Feld — Vergleich mit der Vorgabe der anderen Sprache
    assert "aktuell !== (andere || '').trim()" in html
    assert "this.paymentTermsDe" in html
    assert "this.paymentTermsEn" in html
