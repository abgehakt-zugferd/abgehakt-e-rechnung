"""Ein leeres Kundenland darf nie als leeres CountryID-Element ins XML.

Käufer (BR-57: nicht leere CountryID) und Lieferanschrift (ShipTo) lesen dasselbe
Land, mit derselben Vorgabe „DE“ wie die Formulare (`normalisiere_land`). Die
Datenbank lässt ein leeres Land ohnehin nicht zu (CHECK); dieser Test sichert die
Erzeugung des XML, falls ein Objekt trotzdem ohne Land ankommt.
"""
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from app.services import zugferd_xml
from tests.test_lieferblock_leer import NS, _company, _invoice, _kunde


def _laender(inv):
    wurzel = ET.fromstring(zugferd_xml.generate_xml(inv, _company()))
    return [e.text for e in wurzel.iter(f"{{{NS['ram']}}}CountryID")]


@pytest.mark.parametrize("land", ["", "  ", None])
def test_kaeufer_ohne_land_hat_keine_leere_countryid(land):
    inv = _invoice(_kunde(country=land), delivery_date=date(2026, 6, 15))

    laender = _laender(inv)

    assert laender and all((t or "").strip() for t in laender)


@pytest.mark.parametrize("land", ["", "  ", None])
def test_lieferanschrift_ohne_land_hat_keine_leere_countryid_und_keinen_leeren_block(land):
    inv = _invoice(_kunde(country=land), delivery_date=None)

    wurzel = ET.fromstring(zugferd_xml.generate_xml(inv, _company()))
    block = wurzel.find(".//ram:ApplicableHeaderTradeDelivery", NS)

    assert len(block) == 1
    assert block.find("ram:ShipToTradeParty/ram:PostalTradeAddress/ram:CountryID", NS).text == "DE"
    assert [e.tag for e in wurzel.iter() if len(e) == 0 and not (e.text or "").strip()] == []


def test_land_wird_in_beiden_anschriften_gleich_geschrieben():
    inv = _invoice(_kunde(country="at", city="Wien", zip_code="1010"), delivery_date=None)

    # Verkäufer, Käufer, Lieferanschrift
    assert _laender(inv) == ["DE", "AT", "AT"]
