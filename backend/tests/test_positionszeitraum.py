"""Leistungszeitraum je Position (BT-134/135).

Eine Quartalsrechnung über drei Monate braucht je Monat eine Position mit eigenem
Zeitraum, maschinenlesbar und im PDF sichtbar. Der Kopfzeitraum (BT-73/74) bleibt
die Pflichtangabe nach § 14 Abs. 4 Nr. 6 UStG; die Positionszeiträume sind eine
optionale Aufschlüsselung und ersetzen ihn nicht. Gegrillt am 2026-10-02:
kein abgeleiteter Kopfzeitraum, weil er Daten erzeugte, die niemand eingegeben hat.
"""
import uuid
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.customer import Customer
from app.models.invoice import Invoice

from app.services import mustang, zugferd_xml
from tests.factories import orm_company, orm_invoice, orm_item

RAM = "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}"
UDT = "{urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100}"


def _quartal():
    juli = orm_item(1, "1", "11.56", "19", description="Abo")
    juli.leistung_von, juli.leistung_bis = date(2026, 7, 1), date(2026, 7, 31)
    august = orm_item(2, "1", "11.56", "19", description="Abo")
    august.leistung_von, august.leistung_bis = date(2026, 8, 1), date(2026, 8, 31)
    pauschale = orm_item(3, "1", "5.00", "19", description="Porto")
    return orm_invoice([juli, august, pauschale],
                       service_period_start=date(2026, 7, 1),
                       service_period_end=date(2026, 8, 31))


def _zeile(xml: str, nr: int):
    for zeile in ET.fromstring(xml.encode("utf-8")).iter(f"{RAM}IncludedSupplyChainTradeLineItem"):
        if zeile.findtext(f"{RAM}AssociatedDocumentLineDocument/{RAM}LineID") == str(nr):
            return zeile.find(f"{RAM}SpecifiedLineTradeSettlement")
    raise AssertionError(f"Position {nr} fehlt")


def test_positionszeitraum_steht_als_bt134_135_zwischen_steuer_und_summe(tmp_path):
    xml = zugferd_xml.generate_xml(_quartal(), orm_company())

    juli = _zeile(xml, 1)
    assert [k.tag for k in juli] == [
        f"{RAM}ApplicableTradeTax", f"{RAM}BillingSpecifiedPeriod",
        f"{RAM}SpecifiedTradeSettlementLineMonetarySummation",
    ]
    periode = juli.find(f"{RAM}BillingSpecifiedPeriod")
    assert periode.findtext(f"{RAM}StartDateTime/{UDT}DateTimeString") == "20260701"
    assert periode.findtext(f"{RAM}EndDateTime/{UDT}DateTimeString") == "20260731"
    assert _zeile(xml, 2).findtext(
        f"{RAM}BillingSpecifiedPeriod/{RAM}StartDateTime/{UDT}DateTimeString") == "20260801"
    assert _zeile(xml, 3).find(f"{RAM}BillingSpecifiedPeriod") is None

    pfad = tmp_path / "beleg.xml"
    pfad.write_text(xml, encoding="utf-8")
    befund = mustang.validate(pfad)
    assert befund["is_valid"], befund["errors"]


@pytest.mark.parametrize("von, bis", [
    (date(2026, 7, 1), None),
    (None, date(2026, 7, 31)),
    (date(2026, 7, 31), date(2026, 7, 1)),
])
def test_datenbank_lehnt_halben_oder_verdrehten_zeitraum_ab(pg_session, von, bis):
    """Wer an der Anwendung vorbei schreibt, kommt an der Constraint nicht vorbei."""
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Probe Kunde GmbH",
                     address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(kunde)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=date(2026, 7, 8), due_date=date(2026, 7, 22), currency="EUR",
                  status="draft", net_total=Decimal("1"), tax_total=Decimal("0"),
                  gross_total=Decimal("1"))
    pg_session.add(inv)
    pg_session.flush()

    with pytest.raises(IntegrityError, match="ck_invoice_items_leistung"):
        pg_session.execute(text(
            "INSERT INTO invoice_items (invoice_id, position, description, unit, quantity, "
            "unit_price, tax_rate, net_amount, tax_amount, gross_amount, leistung_von, leistung_bis) "
            "VALUES (:inv, 1, 'Abo', 'Stück', 1, 1, 0, 1, 0, 1, :von, :bis)"
        ), {"inv": inv.id, "von": von, "bis": bis})
    pg_session.rollback()


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_pdf_zeigt_den_positionszeitraum_unter_der_beschreibung(tmp_path, sprache):
    from pypdf import PdfReader

    from app.services import pdf_generator
    from app.services.belegsprache import darstellung

    inv = _quartal()
    inv.document_language = sprache
    d = darstellung(sprache)
    out = tmp_path / "beleg.pdf"

    pdf_generator.generate_pdf(inv, orm_company(), out)

    text = " ".join("".join(p.extract_text() for p in PdfReader(str(out)).pages).split())
    juli = f"{d.label_leistungszeitraum} {d.format_datum(date(2026, 7, 1))} – {d.format_datum(date(2026, 7, 31))}"
    august = f"{d.label_leistungszeitraum} {d.format_datum(date(2026, 8, 1))} – {d.format_datum(date(2026, 8, 31))}"
    assert f"Abo {juli}" in text
    assert f"Abo {august}" in text
    assert "Porto 1" in text


def test_entwurf_aus_beleg_bindet_den_positionszeitraum_an_den_bestand():
    """Der Leistungszeitraum stammt bei einem Beleg-Entwurf aus dem signierten Beleg
    (belegsperre.py). Ein im Formular eingetragener Positionszeitraum könnte ihm
    widersprechen; er wird deshalb aus dem Bestand genommen wie Menge und Preis.
    Gefunden im Gegenspieler-Review 2026-10-02."""
    from types import SimpleNamespace

    from app.services import belegsperre

    alt = SimpleNamespace(position=1, quantity=Decimal("1"), unit_price=Decimal("10"),
                          unit="Stück", leistung_von=None, leistung_bis=None)
    inv = SimpleNamespace(items=[alt])
    eingabe = [{"description": "Neu", "quantity": "9", "unit_price": "99", "unit": "Stunde",
                "leistung_von": "2026-07-01", "leistung_bis": "2026-07-31"}]

    gebunden = belegsperre.positionen_binden(inv, eingabe)

    assert (gebunden[0]["leistung_von"], gebunden[0]["leistung_bis"]) == ("", "")
    assert gebunden[0]["description"] == "Neu"
