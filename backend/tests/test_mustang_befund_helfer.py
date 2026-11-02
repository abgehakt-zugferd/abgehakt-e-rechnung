"""Vertrag der Erweiterungen in `tests/helpers/mustang_befund.py`.

Jede Zusicherung ueber den Mustang-Rohbericht ueberspringt ausdruecklich, wenn
Mustang nicht ausfuehrbar war, und wertet sonst den Bericht aus.
"""
import pytest

from tests.helpers import mustang_befund

UNGEMESSEN = {"is_valid": False, "raw": "", "errors": [], "nicht_ausfuehrbar": True,
              "grund": "JAR fehlt"}


def _gemessen(raw: str, is_valid: bool = True) -> dict:
    return {"is_valid": is_valid, "raw": raw, "errors": [], "nicht_ausfuehrbar": False}


@pytest.mark.parametrize("pruefung", [
    lambda b: mustang_befund.gueltig_mit_xml(b),
    lambda b: mustang_befund.bericht_enthaelt(b, "XML:valid"),
    lambda b: mustang_befund.bericht_ohne(b, "BR-DE-2]"),
])
def test_rohbericht_zusicherungen_ueberspringen_wenn_nicht_gemessen(pruefung):
    with pytest.raises(pytest.skip.Exception, match="Mustang fehlt, nicht gemessen: JAR fehlt"):
        pruefung(UNGEMESSEN)


def test_gueltig_mit_xml_laesst_xml_valid_durch():
    mustang_befund.gueltig_mit_xml(_gemessen("Parsed PDF:valid\nXML:valid"))


def test_gueltig_mit_xml_verlangt_xml_valid_nicht_nur_is_valid():
    with pytest.raises(AssertionError):
        mustang_befund.gueltig_mit_xml(_gemessen("Parsed PDF:valid"))


def test_gueltig_mit_xml_scheitert_bei_ungueltig():
    with pytest.raises(AssertionError):
        mustang_befund.gueltig_mit_xml(_gemessen("XML:valid", is_valid=False))


def test_bericht_enthaelt_scheitert_bei_fehlendem_marker():
    with pytest.raises(AssertionError):
        mustang_befund.bericht_enthaelt(_gemessen("nichts"), "isCompliant=true")


def test_bericht_ohne_scheitert_bei_vorhandenem_marker():
    with pytest.raises(AssertionError):
        mustang_befund.bericht_ohne(_gemessen("[error] BR-DE-2] fehlt"), "BR-DE-2]")


def test_bericht_ohne_laesst_gemessenen_sauberen_bericht_durch():
    mustang_befund.bericht_ohne(_gemessen("XML:valid"), "BR-DE-2]")
