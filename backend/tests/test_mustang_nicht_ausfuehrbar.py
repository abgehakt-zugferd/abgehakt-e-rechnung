"""#252: „nicht ausfuehrbar" ist nicht „ungueltig".

Fehlt das JAR oder Java, oder reisst die Zeitgrenze, wurde nichts gemessen. Das
Ergebnis von `mustang.validate` muss das sagen, sonst liest ein Test `[] assert
False` als „XML ungueltig". Fuer Produktivcode bleibt es dabei: nicht
ausfuehrbar ist nie gueltig.
"""
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services import mustang
from tests.helpers import mustang_befund

FEHLENDES_JAR = Path("/nicht/vorhanden/Mustang-CLI.jar")


def _ohne_jar():
    return patch("app.services.mustang.JAR", str(FEHLENDES_JAR))


def _lauf(stdout="", stderr="", rc=0):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_fehlendes_jar_ist_nicht_ausfuehrbar_und_nicht_gueltig():
    with _ohne_jar():
        befund = mustang.validate(Path("/tmp/egal.xml"))

    assert befund["nicht_ausfuehrbar"] is True
    assert befund["is_valid"] is False
    assert "JAR" in befund["grund"]
    assert befund["grund"] in befund["raw"]


def test_fehlendes_java_ist_nicht_ausfuehrbar():
    with patch("app.services.mustang.jar_available", return_value=True), \
         patch("app.services.mustang.subprocess.run", side_effect=FileNotFoundError("java")):
        befund = mustang.validate(Path("/tmp/egal.xml"))

    assert befund["nicht_ausfuehrbar"] is True
    assert befund["is_valid"] is False
    assert "Java" in befund["grund"]


def test_zeitgrenze_ist_nicht_ausfuehrbar():
    def abbruch(*a, **k):
        raise subprocess.TimeoutExpired(cmd="java", timeout=60)

    with patch("app.services.mustang.jar_available", return_value=True), \
         patch("app.services.mustang.subprocess.run", side_effect=abbruch):
        befund = mustang.validate(Path("/tmp/egal.xml"))

    assert befund["nicht_ausfuehrbar"] is True
    assert "Zeit" in befund["grund"]


def test_echter_befund_ist_ausfuehrbar_auch_wenn_ungueltig():
    with patch("app.services.mustang.jar_available", return_value=True), \
         patch("app.services.mustang.subprocess.run",
               return_value=_lauf(stdout="[error] BR-CO-26 fehlt", rc=1)):
        befund = mustang.validate(Path("/tmp/egal.xml"))

    assert befund["nicht_ausfuehrbar"] is False
    assert befund["is_valid"] is False
    assert befund["errors"] == ["[error] BR-CO-26 fehlt"]


def test_echter_gueltiger_befund_ist_ausfuehrbar():
    with patch("app.services.mustang.jar_available", return_value=True), \
         patch("app.services.mustang.subprocess.run",
               return_value=_lauf(stdout="XML:valid", rc=0)):
        befund = mustang.validate(Path("/tmp/egal.xml"))

    assert befund["nicht_ausfuehrbar"] is False
    assert mustang.ist_gueltige_e_rechnung(befund)


def test_nicht_ausfuehrbar_ist_nie_eine_gueltige_e_rechnung():
    # Auch ein (fehlerhaft) gesetztes is_valid + XML:valid darf es nicht freigeben.
    befund = {"is_valid": True, "raw": "XML:valid", "nicht_ausfuehrbar": True}
    assert mustang.ist_gueltige_e_rechnung(befund) is False


def test_combine_und_extract_scheitern_geordnet_ohne_jar(tmp_path):
    with _ohne_jar():
        assert mustang.combine(tmp_path / "a.pdf", tmp_path / "a.xml", tmp_path / "o.pdf") is False
        assert mustang.extract_xml(tmp_path / "a.pdf", tmp_path / "o.xml") is False


# ── Testhelfer ────────────────────────────────────────────────────────────────

def test_helfer_ueberspringt_ausdruecklich_wenn_nicht_gemessen():
    with _ohne_jar():
        befund = mustang.validate(Path("/tmp/egal.xml"))
    with pytest.raises(pytest.skip.Exception, match="Mustang fehlt, nicht gemessen"):
        mustang_befund.gueltig(befund)


def test_helfer_scheitert_bei_gemessen_ungueltig():
    befund = {"is_valid": False, "raw": "", "errors": ["[error] x"], "nicht_ausfuehrbar": False}
    with pytest.raises(AssertionError):
        mustang_befund.gueltig(befund)


def test_helfer_laesst_gueltigen_befund_durch():
    mustang_befund.gueltig({"is_valid": True, "raw": "XML:valid", "errors": [],
                            "nicht_ausfuehrbar": False})


def test_helfer_ungueltig_ueberspringt_ebenfalls_ungemessen():
    befund = {"is_valid": False, "raw": "", "errors": [], "nicht_ausfuehrbar": True,
              "grund": "JAR fehlt"}
    with pytest.raises(pytest.skip.Exception, match="nicht gemessen"):
        mustang_befund.ungueltig(befund)
