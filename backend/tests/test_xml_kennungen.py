"""Kennungen in der E-Rechnung, die das PDF schon zeigt: Kundennummer (BT-46).

Das PDF druckt die Kundennummer im Kopf; die XML, die seit 2025 Vorrang hat,
kannte sie nicht. Zwei Teile desselben Belegs sagten damit Verschiedenes.
"""
import xml.etree.ElementTree as ET

from app.services import mustang, zugferd_xml
from tests.factories import orm_company, orm_customer, orm_invoice, orm_invoice_for, orm_item

RAM = "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}"


def _kaeufer(xml: str):
    return ET.fromstring(xml.encode("utf-8")).find(f".//{RAM}BuyerTradeParty")


def _gueltig(xml: str, tmp_path) -> None:
    pfad = tmp_path / "beleg.xml"
    pfad.write_text(xml, encoding="utf-8")
    befund = mustang.validate(pfad)
    assert befund["is_valid"], befund["errors"]


def test_kundennummer_steht_als_bt46_in_der_xml(tmp_path):
    kunde = orm_customer(customer_number="K-PROBE-0042")
    xml = zugferd_xml.generate_xml(orm_invoice_for(kunde), orm_company())

    assert _kaeufer(xml).findtext(f"{RAM}ID") == "K-PROBE-0042"
    _gueltig(xml, tmp_path)


def _produkt(xml: str, nr: int):
    for zeile in ET.fromstring(xml.encode("utf-8")).iter(f"{RAM}IncludedSupplyChainTradeLineItem"):
        if zeile.findtext(f"{RAM}AssociatedDocumentLineDocument/{RAM}LineID") == str(nr):
            return zeile.find(f"{RAM}SpecifiedTradeProduct")
    raise AssertionError(f"Position {nr} fehlt")


def test_artikelnummer_steht_als_bt155_vor_dem_namen(tmp_path):
    mit = orm_item(1, "1", "100.00", "19", description="Beratung")
    mit.artikelnummer = "00950"
    ohne = orm_item(2, "1", "50.00", "19", description="Reisekosten")
    inv = orm_invoice([mit, ohne])
    xml = zugferd_xml.generate_xml(inv, orm_company())

    produkt = _produkt(xml, 1)
    assert [k.tag for k in produkt] == [f"{RAM}SellerAssignedID", f"{RAM}Name"]
    assert produkt.findtext(f"{RAM}SellerAssignedID") == "00950"
    assert _produkt(xml, 2).find(f"{RAM}SellerAssignedID") is None
    _gueltig(xml, tmp_path)
