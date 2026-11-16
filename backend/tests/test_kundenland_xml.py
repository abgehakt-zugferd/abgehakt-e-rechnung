"""Im Lesepfad wird kein Land erfunden (#299).

Die Vorgabe „DE“ (`normalisiere_land`) gilt nur im Formularweg. Wer ein gespeichertes
Land liest (XML, Belegrollen), nimmt `bereinige_land`: ein leeres Land bleibt leer.

- Käufer ohne Land: kein CountryID-Element. Mustang meldet dafür als FEHLER BR-11
  (Käuferanschrift ohne BT-55; dazu Schema- und FX-SCH-A-000422-Fehler, am echten
  Bericht abgelesen), das Finalisieren wird also blockiert.
- Verkäufer (eigene Firma) ohne Land: ebenfalls kein CountryID-Element, Mustang meldet
  BR-09 (BT-40) als Fehler.
- Lieferanschrift ohne Land: kein ShipToTradeParty. Der Block bleibt leer, Mustang
  meldet die Warnung PEPPOL-EN16931-R008, die Rückfrage beim Finalisieren greift.
Die Datenbank lässt ein leeres Kundenland ohnehin nicht zu (CHECK); diese Tests
sichern die Erzeugung des XML für Altzeilen.
"""
import xml.etree.ElementTree as ET
from datetime import date

import pytest

from app.laender import bereinige_land
from app.services import mustang as mustang_modul
from app.services import zugferd_xml
from tests.helpers import mustang_befund
from app.services.belegrollen import _partei
from tests.test_lieferblock_leer import NS, _company, _invoice, _kunde


# Am echten Mustang-Bericht abgelesen: Verkäuferanschrift ohne BT-40 (dazu Schemafehler).
REGEL_VERKAEUFER = "BR-09"


def _laender(inv):
    wurzel = ET.fromstring(zugferd_xml.generate_xml(inv, _company()))
    return [e.text for e in wurzel.iter(f"{{{NS['ram']}}}CountryID")]


@pytest.mark.parametrize("land", ["", "  ", None])
def test_kaeufer_ohne_land_schreibt_keine_countryid_und_erfindet_kein_de(land):
    inv = _invoice(_kunde(country=land), delivery_date=date(2026, 6, 15))

    wurzel = ET.fromstring(zugferd_xml.generate_xml(inv, _company()))
    adresse = wurzel.find(".//ram:BuyerTradeParty/ram:PostalTradeAddress", NS)

    assert adresse.find("ram:CountryID", NS) is None
    assert _laender(inv) == ["DE"]   # nur der Verkäufer
    assert [e.tag for e in wurzel.iter() if len(e) == 0 and not (e.text or "").strip()] == []


@pytest.mark.parametrize("land", ["", "  ", None])
def test_lieferanschrift_ohne_land_schreibt_keinen_shipto_und_erfindet_kein_de(land):
    inv = _invoice(_kunde(country=land), delivery_date=None)

    wurzel = ET.fromstring(zugferd_xml.generate_xml(inv, _company()))
    block = wurzel.find(".//ram:ApplicableHeaderTradeDelivery", NS)

    assert block.find("ram:ShipToTradeParty", NS) is None
    assert len(block) == 0   # bleibt leer: Mustang meldet R008, die Rückfrage greift


def test_lesepfad_ersetzt_kein_leeres_land():
    assert [bereinige_land(w) for w in ("", "  ", None, " at ")] == ["", "", "", "AT"]
    assert _partei(_kunde(country=""), firma=False).country == ""


def test_land_wird_in_beiden_anschriften_gleich_geschrieben():
    inv = _invoice(_kunde(country="at", city="Wien", zip_code="1010"), delivery_date=None)

    # Verkäufer, Käufer, Lieferanschrift
    assert _laender(inv) == ["DE", "AT", "AT"]


# -- Echter Mustang ----------------------------------------------------------

def _mustang(inv, firma=None):
    import os, tempfile
    from pathlib import Path

    from app.services import mustang
    fd, name = tempfile.mkstemp(suffix=".xml")
    try:
        os.write(fd, zugferd_xml.generate_xml(inv, firma or _company()).encode("utf-8"))
        os.close(fd)
        return mustang.validate(Path(name))
    finally:
        Path(name).unlink(missing_ok=True)


def _befunde(ergebnis, schwere):
    return {b["regel"] for b in ergebnis["befunde"] if b["schwere"] == schwere}


@pytest.mark.skipif(not mustang_modul.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_mustang_blockiert_kaeufer_ohne_land_mit_br_11():
    ergebnis = _mustang(_invoice(_kunde(country=""), delivery_date=date(2026, 6, 15)))

    mustang_befund.ungueltig(ergebnis)
    assert "BR-11" in _befunde(ergebnis, "error")
    assert mustang_modul.ist_gueltige_e_rechnung(ergebnis) is False


@pytest.mark.skipif(not mustang_modul.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_mustang_meldet_lieferblock_ohne_land_als_r008_warnung():
    ergebnis = _mustang(_invoice(_kunde(country=""), delivery_date=None))

    mustang_befund.ungueltig(ergebnis)   # der Käufer ohne Land bleibt ein Fehler
    assert "PEPPOL-EN16931-R008" in _befunde(ergebnis, "warning")


@pytest.mark.skipif(not mustang_modul.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_mustang_blockiert_verkaeufer_ohne_land_mit_regel():
    """Eigene Firma mit country='': kein erfundenes DE, Mustang meldet einen Fehler."""
    inv = _invoice(_kunde(), delivery_date=date(2026, 6, 15))
    wurzel = ET.fromstring(zugferd_xml.generate_xml(inv, _company(country="")))
    verkaeufer = wurzel.find(".//ram:SellerTradeParty/ram:PostalTradeAddress", NS)
    assert verkaeufer.find("ram:CountryID", NS) is None

    ergebnis = _mustang(inv, _company(country=""))

    mustang_befund.ungueltig(ergebnis)
    assert REGEL_VERKAEUFER in _befunde(ergebnis, "error")
    assert mustang_modul.ist_gueltige_e_rechnung(ergebnis) is False
