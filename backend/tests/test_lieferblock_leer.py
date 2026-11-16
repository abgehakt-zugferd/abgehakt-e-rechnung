"""Leerer Lieferblock im XML (PEPPOL-EN16931-R008, #299).

Eine Rechnung mit Leistungszeitraum, aber ohne Leistungsdatum erzeugte ein leeres
<ram:ApplicableHeaderTradeDelivery>. Mustang meldet das als Warnung, DATEV zeigt
die Rechnung als „E-Rechnung mit Formatfehlern“.

Nähte: zugferd_xml.generate_xml (erzeugtes XML), mustang.validate (Auswertung des
Prüfberichts), rechnung.pruefung.run_validation (gespeichertes Prüfergebnis).
"""
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.customer import Customer
from app.services import mustang, zugferd_xml
from app.services.rechnung import pruefung
from tests.helpers import mustang_befund
from tests.test_zugferd_xml_schema import _company, _invoice

NS = {"ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
      "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"}
R008 = "PEPPOL-EN16931-R008"

# Bericht, wie Mustang 2.26 ihn schreibt (gekürzt): Warnungen und Fehler stehen
# als XML-Elemente, nicht als „[warning]“-Zeilen.
BERICHT_WARNUNG = """<?xml version="1.0" encoding="UTF-8"?>
<validation filename="x.xml">
  <xml>
    <messages>
      <warning type="4" location="/*:CrossIndustryInvoice[1]/*:ApplicableHeaderTradeDelivery[1]" criterion="false">[PEPPOL-EN16931-R008]-Document MUST not contain empty elements. (still status warning) [ID PEPPOL-EN16931-R008] from /xslt/ZF_250/FACTUR-X_EN16931.xslt)</warning>
    </messages>
    <summary status="valid"/>
  </xml>
</validation>
[main] INFO org.mustangproject.validator.ZUGFeRDValidator - Parsed PDF:absent XML:valid Errors:[4] ErrorIDs: [PEPPOL-EN16931-R008]
"""
BERICHT_FEHLER = """<validation>
  <xml>
    <messages>
      <error type="4" location="/*:CrossIndustryInvoice[1]" criterion="x">[BR-07]-An Invoice shall contain the Buyer name (BT-44). [ID BR-07] from /xslt/ZF_250/FACTUR-X_EN16931.xslt)</error>
      <warning type="10">Arithmetical issue:Payable total in XML is 999.00</warning>
    </messages>
    <summary status="invalid"/>
  </xml>
</validation>
"""


def _kunde(**over):
    kw = dict(name="Kunde GmbH", address_line1="Weg 1", zip_code="10115", city="Berlin",
              country="DE")
    kw.update(over)
    return Customer(**kw)


def _ohne_nullsteuer(inv):
    pos = inv.items[0]
    pos.tax_rate = Decimal("0")
    pos.tax_amount = Decimal("0")
    pos.gross_amount = pos.net_amount
    inv.tax_total = Decimal("0")
    inv.gross_total = inv.net_total
    return inv


def _lieferblock(inv):
    wurzel = ET.fromstring(zugferd_xml.generate_xml(inv, _company()))
    return wurzel.find(".//ram:ApplicableHeaderTradeDelivery", NS)


def _ereignis(block):
    knoten = block.find("ram:ActualDeliverySupplyChainEvent/ram:OccurrenceDateTime/udt:DateTimeString", NS)
    return None if knoten is None else (knoten.get("format"), knoten.text)


# -- 1. Lieferblock ---------------------------------------------------------

def test_nur_zeitraum_schreibt_das_ende_als_lieferdatum():
    inv = _invoice(_kunde(), delivery_date=None,
                   service_period_start=date(2026, 6, 1), service_period_end=date(2026, 6, 30))

    assert _ereignis(_lieferblock(inv)) == ("102", "20260630")
    assert inv.delivery_date is None  # nur das XML ändert sich, nicht der Beleg


def test_leistungsdatum_hat_vorrang_vor_dem_zeitraumende():
    inv = _invoice(_kunde(), delivery_date=date(2026, 6, 15),
                   service_period_start=date(2026, 6, 1), service_period_end=date(2026, 6, 30))

    assert _ereignis(_lieferblock(inv)) == ("102", "20260615")


def test_anzahlungsrechnung_schreibt_kein_lieferereignis_aus_dem_zeitraum():
    """386: Der Zeitraum liegt in der Zukunft (BG-14 „voraussichtlich“). Ein
    tatsächliches Lieferereignis würde behaupten, es sei schon geliefert worden."""
    inv = _invoice(_kunde(), delivery_date=None, invoice_type="prepayment",
                   service_period_start=date(2026, 12, 1), service_period_end=date(2026, 12, 31))

    assert _ereignis(_lieferblock(inv)) is None


def test_kleinbetrag_ohne_datum_und_zeitraum_behaelt_den_leeren_block():
    """§ 33 UStDV (#47): Der Block muss als Element stehen (CII-Schema), ohne
    Inhalt. Das ist der eine bekannte leere Fall und wird nicht aufgefüllt."""
    inv = _invoice(_kunde(), delivery_date=None)

    block = _lieferblock(inv)

    assert block is not None
    assert len(block) == 0


# -- 4. Wächter: keine leeren Elemente -------------------------------------

def _s_mit_datum():
    return _invoice(_kunde()), False


def _s_nur_zeitraum():
    return _invoice(_kunde(), delivery_date=None, service_period_start=date(2026, 6, 1),
                    service_period_end=date(2026, 6, 30)), False


def _ae_zeitraum():
    inv = _invoice(_kunde(country="AT", city="Wien", zip_code="1010", vat_id="ATU12345678"),
                   delivery_date=None, tax_category="AE",
                   service_period_start=date(2026, 6, 1), service_period_end=date(2026, 6, 30))
    return _ohne_nullsteuer(inv), False


def _k_innergemeinschaftlich():
    inv = _invoice(_kunde(country="AT", city="Wien", zip_code="1010", vat_id="ATU12345678"),
                   tax_category="K")
    return _ohne_nullsteuer(inv), False


def _kleinbetrag_ohne_datum():
    return _invoice(_kunde(), delivery_date=None), True


@pytest.mark.parametrize("bauen", [
    _s_mit_datum, _s_nur_zeitraum, _ae_zeitraum, _k_innergemeinschaftlich,
    _kleinbetrag_ohne_datum,
])
def test_xml_enthaelt_keine_leeren_elemente(bauen):
    inv, kleinbetrag = bauen()
    wurzel = ET.fromstring(zugferd_xml.generate_xml(inv, _company()))

    leer = [e.tag.rsplit("}", 1)[-1] for e in wurzel.iter()
            if len(e) == 0 and not (e.text or "").strip()]
    # Der Kleinbetrag ohne Datum und Zeitraum ist der dokumentierte Sonderfall.
    erlaubt = ["ApplicableHeaderTradeDelivery"] if kleinbetrag else []
    assert leer == erlaubt


# -- 2. Mustang-Bericht auswerten ------------------------------------------

def _validate_mit(stdout, rc=0):
    with patch.object(mustang, "_run", return_value=(stdout, "", rc)):
        return mustang.validate(Path("x.xml"))


def test_warnungen_aus_den_warning_elementen_werden_gelesen():
    ergebnis = _validate_mit(BERICHT_WARNUNG)

    assert len(ergebnis["warnings"]) == 1
    assert ergebnis["warnings"][0].startswith(f"[{R008}]-Document MUST not contain empty elements.")
    assert ergebnis["is_valid"] is True


def test_fehler_aus_den_error_elementen_werden_gelesen_ohne_die_wertung_zu_aendern():
    ergebnis = _validate_mit(BERICHT_FEHLER, rc=0)

    assert [f for f in ergebnis["errors"] if f.startswith("[BR-07]")]
    assert ergebnis["warnings"] == ["Arithmetical issue:Payable total in XML is 999.00"]
    # is_valid hängt weiter nur an Rückgabecode und [error]-Marker.
    assert ergebnis["is_valid"] is True
    assert _validate_mit(BERICHT_FEHLER, rc=1)["is_valid"] is False


# -- 3. Prüfergebnis --------------------------------------------------------

class _Sitzung:
    def __init__(self):
        self.eintraege = []

    def add(self, eintrag):
        self.eintraege.append(eintrag)


def _pruefen(mustang_ergebnis):
    inv = _invoice(_kunde(), delivery_date=None,
                   service_period_start=date(2026, 6, 1), service_period_end=date(2026, 6, 30))
    inv.zugferd_xml = zugferd_xml.generate_xml(inv, _company())
    with patch.object(mustang, "validate", return_value=mustang_ergebnis):
        return pruefung.run_validation(_Sitzung(), inv, _company())


def test_mustang_warnung_steht_im_pruefergebnis_und_sperrt_nichts():
    gemessen = {"is_valid": True, "nicht_ausfuehrbar": False, "grund": "", "errors": [],
                "raw": "XML:valid", "warnings": [
                    f"[{R008}]-Document MUST not contain empty elements. (still status warning) "
                    f"[ID {R008}] from /xslt/ZF_250/FACTUR-X_EN16931.xslt)"]}

    vr = _pruefen(gemessen)

    mustang_warnungen = [w for w in vr.warnings if w["code"].startswith("MUSTANG_")]
    assert [w["code"] for w in mustang_warnungen] == [f"MUSTANG_{R008}"]
    assert mustang_warnungen[0]["severity"] == "warning"
    assert "empty elements" in mustang_warnungen[0]["message"]
    assert "[ID" not in mustang_warnungen[0]["message"]
    assert vr.is_valid is True


def test_mustang_warnung_ohne_regelkennung_bekommt_allgemeinen_code():
    gemessen = {"is_valid": True, "nicht_ausfuehrbar": False, "grund": "", "errors": [],
                "raw": "XML:valid", "warnings": ["Arithmetical issue:Payable total is off"]}

    vr = _pruefen(gemessen)

    assert [w["code"] for w in vr.warnings if w["code"].startswith("MUSTANG_")] == ["MUSTANG_WARNUNG"]


# -- 5. Mustang wirklich ----------------------------------------------------

@pytest.mark.skipif(not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_mustang_meldet_fuer_rechnung_mit_zeitraum_keinen_leeren_block():
    inv = _invoice(_kunde(), delivery_date=None,
                   service_period_start=date(2026, 6, 1), service_period_end=date(2026, 6, 30))
    xml = zugferd_xml.generate_xml(inv, _company())
    fd, name = tempfile.mkstemp(suffix=".xml")
    datei = Path(name)
    try:
        os.write(fd, xml.encode("utf-8"))
        os.close(fd)
        ergebnis = mustang.validate(datei)
    finally:
        datei.unlink(missing_ok=True)

    mustang_befund.gueltig_mit_xml(ergebnis)
    mustang_befund.bericht_ohne(ergebnis, R008)
    assert ergebnis["warnings"] == []
