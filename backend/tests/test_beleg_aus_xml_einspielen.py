"""Einspielen finalisierter Belege aus XML/PDF: TypeCode und Honorargutschrift."""

import subprocess
import sys
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
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

BACKEND = Path(__file__).resolve().parents[1]


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


def _xml_fuer(
    nummer: str, kunde: Customer, *, invoice_type: str | None, rate: Decimal | None = None,
) -> str:
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
    if rate is None:
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
    pg_session.expunge_all()
    frisch = pg_session.query(Invoice).filter(Invoice.invoice_number == nummer).one()
    assert [(i.position, i.tax_rate) for i in frisch.items] == [(1, Decimal("7.00"))]


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


def test_einspielen_prueft_den_satz_jeder_position(pg_session, capsys):
    """Kopf S passt zu regelbesteuert, die Position traegt aber 19 statt 7 %.

    Die Pruefung lief vor dem Anlegen der Positionen und sah deshalb nur den
    Kopf; eine solche 389 kam durch.
    """
    nummer = "HG-EIN-005"
    kunde = _kunde(pg_session, ust_status="regelbesteuert", gutschriftempfaenger=True)
    xml = _xml_fuer(nummer, kunde, invoice_type="self_billing", rate=Decimal("19.00"))
    _lege_xml_und_pdf(nummer, xml)

    einspielen([nummer], db=pg_session)

    out = capsys.readouterr().out
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.invoice_number == nummer).count() == 0
    assert "UST_STATUS_STEUER_MISMATCH" in out


def test_einspielen_weist_doctype_entity_kaskade_ab(pg_session, capsys):
    """XML mit DOCTYPE und Entity-Kaskade (kleines Billion Laughs) wird abgewiesen.

    Fremde XML darf nie mit xml.etree geparsed werden: Entities im DTD werden
    sonst expandiert. defusedxml wirft EntitiesForbidden (ValueError-Subklasse),
    das Skript uebersetzt das in seine FEHLER-Meldung.
    """
    nummer = "RE-EIN-006"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE beleg [\n"
        '  <!ENTITY stufe1 "probe ">\n'
        '  <!ENTITY stufe2 "&stufe1;&stufe1;&stufe1;&stufe1;&stufe1;&stufe1;&stufe1;&stufe1;">\n'
        '  <!ENTITY stufe3 "&stufe2;&stufe2;&stufe2;&stufe2;&stufe2;&stufe2;&stufe2;&stufe2;">\n'
        '  <!ENTITY stufe4 "&stufe3;&stufe3;&stufe3;&stufe3;&stufe3;&stufe3;&stufe3;&stufe3;">\n'
        "]>\n"
        "<beleg>&stufe4;</beleg>\n"
    )
    _lege_xml_und_pdf(nummer, xml)

    einspielen([nummer], db=pg_session)

    out = capsys.readouterr().out
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.invoice_number == nummer).count() == 0
    assert "FEHLER" in out
    assert "EntitiesForbidden" in out


def test_skript_ohne_nummern_bricht_vor_der_datenbank_ab():
    """Ohne Nummern-Argument MUSS das Skript abbrechen (Exit != 0).

    argparse meldet das fehlende Pflichtargument auf stderr und steigt aus,
    bevor get_settings()/SessionLocal die Datenbank anfassen. Das Skript
    darf nie mit einer Default-Liste von allein loslaufen.
    """
    result = subprocess.run(
        [sys.executable, "scripts/beleg_aus_xml_einspielen.py"],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "nummern" in result.stderr
