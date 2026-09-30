"""Einspielen finalisierter Belege aus XML/PDF: TypeCode und Honorargutschrift."""

import uuid
from datetime import date
from decimal import Decimal
from xml.etree import ElementTree as ET

from app.config import get_settings
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services.zugferd_xml import generate_xml
from scripts.beleg_aus_xml_einspielen import einspielen
from tests.factories import company_stub, customer_stub, item_stub, zugferd_invoice_stub
from tests.probe_daten import STEUER_PROBE_ZEHN, UST_DE_PROBE, UST_DE_PROBE_2

_NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
}


def _kunde(pg_session, **over):
    kw = dict(
        customer_number=f"K-EIN-{uuid.uuid4().hex[:8]}",
        name="Probe Empfaenger GmbH",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        vat_id=UST_DE_PROBE_2,
        gutschriftempfaenger=True,
        ust_status="ungeklaert",
        tax_number=STEUER_PROBE_ZEHN,
    )
    kw.update(over)
    kunde = Customer(**kw)
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def _lege_xml_und_pdf(nummer: str, xml: str) -> None:
    settings = get_settings()
    (settings.storage_path / "xml" / f"{nummer}.xml").write_text(xml, encoding="utf-8")
    (settings.storage_path / "pdfs" / f"{nummer}.pdf").write_bytes(b"%PDF-1.4 probe")


def _xml_fuer(nummer: str, kunde: Customer, *, invoice_type: str | None) -> str:
    company = company_stub(
        name="Muster Handwerk GmbH",
        tax_number=STEUER_PROBE_ZEHN,
        vat_id=UST_DE_PROBE,
    )
    cust = customer_stub(
        name=kunde.name,
        address_line1=kunde.address_line1,
        zip_code=kunde.zip_code,
        city=kunde.city,
        country=kunde.country,
        vat_id=kunde.vat_id,
    )
    rate = Decimal("7.00") if invoice_type == "self_billing" else Decimal("19.00")
    netto = Decimal("100.00")
    steuer = (netto * rate / Decimal("100")).quantize(Decimal("0.01"))
    inv = zugferd_invoice_stub(
        invoice_number=nummer,
        invoice_type=invoice_type,
        customer=cust,
        issue_date=date(2026, 7, 8),
        due_date=date(2026, 7, 22),
        delivery_date=date(2026, 7, 8),
        tax_category="S",
        items=[item_stub(
            tax_rate=rate,
            net_amount=netto,
            tax_amount=steuer,
            gross_amount=netto + steuer,
            quantity=Decimal("1.0000"),
            unit_price=netto,
        )],
        net_total=netto,
        tax_total=steuer,
        gross_total=netto + steuer,
    )
    return generate_xml(inv, company)


def _mit_typecode(xml: str, code: str) -> str:
    root = ET.fromstring(xml)
    el = root.find(".//rsm:ExchangedDocument/ram:TypeCode", _NS)
    assert el is not None
    el.text = code
    return ET.tostring(root, encoding="unicode")


def test_einspielen_weist_389_bei_ungeklaertem_status_ab(pg_session, capsys):
    """Durchstich: Honorargutschrift fuer ungeklaerten Kunden wird nicht angelegt."""
    nummer = "HG-EIN-001"
    kunde = _kunde(pg_session, ust_status="ungeklaert", gutschriftempfaenger=True)
    _lege_xml_und_pdf(nummer, _xml_fuer(nummer, kunde, invoice_type="self_billing"))

    einspielen([nummer], db=pg_session)

    out = capsys.readouterr().out
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.invoice_number == nummer).count() == 0
    assert "UST_STATUS_UNGEKLAERT" in out


def test_einspielen_setzt_invoice_type_self_billing_aus_389(pg_session):
    """TypeCode 389 wird ueber belegart auf self_billing abgebildet und gespeichert."""
    nummer = "HG-EIN-002"
    kunde = _kunde(
        pg_session,
        ust_status="regelbesteuert",
        gutschriftempfaenger=True,
        tax_number=STEUER_PROBE_ZEHN,
    )
    _lege_xml_und_pdf(nummer, _xml_fuer(nummer, kunde, invoice_type="self_billing"))

    einspielen([nummer], db=pg_session)

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.invoice_number == nummer).one()
    assert row.status == "issued"
    assert row.invoice_type == "self_billing"


def test_einspielen_standardrechnung_behaelt_invoice_type_none(pg_session):
    """TypeCode 380 bleibt Standard (invoice_type None), sonst unveraendertes Einspielen."""
    nummer = "RE-EIN-003"
    kunde = _kunde(pg_session, ust_status="ungeklaert", gutschriftempfaenger=False)
    _lege_xml_und_pdf(nummer, _xml_fuer(nummer, kunde, invoice_type=None))

    einspielen([nummer], db=pg_session)

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.invoice_number == nummer).one()
    assert row.status == "issued"
    assert row.invoice_type is None


def test_einspielen_weist_unbekannten_typecode_ab(pg_session, capsys):
    """Unbekannter TypeCode bricht diesen Beleg ab, statt ihn als Standard zu speichern."""
    nummer = "RE-EIN-004"
    kunde = _kunde(pg_session)
    xml = _mit_typecode(_xml_fuer(nummer, kunde, invoice_type=None), "999")
    _lege_xml_und_pdf(nummer, xml)

    einspielen([nummer], db=pg_session)

    out = capsys.readouterr().out
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.invoice_number == nummer).count() == 0
    assert "999" in out
    assert "TypeCode" in out or "typecode" in out.lower()
