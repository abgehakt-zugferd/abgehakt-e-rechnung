"""Fehlendes Mustang-JAR ist rot, wenn die Umgebung es erwartet (MUSTANG_ERWARTET=1).

Ohne die Variable (Dev-Schleife im venv) bleibt es bei den sichtbaren Skips mit Grund
(`-rs`). Im Test-Abbild (run-tests.sh) steht sie, das JAR liegt im Abbild; fehlt es dort,
bricht schon der Sitzungsstart ab, statt dutzende Mustang-Tests still zu überspringen.
"""
import pytest

from tests.helpers.mustang_erwartet import jar_fehlt_obwohl_erwartet


@pytest.mark.parametrize("wert", ["1", "true", "ja"])
def test_erwartet_und_fehlt_gibt_eine_meldung(wert):
    meldung = jar_fehlt_obwohl_erwartet({"MUSTANG_ERWARTET": wert}, jar_da=False)

    assert meldung and "MUSTANG_ERWARTET" in meldung


@pytest.mark.parametrize("umgebung,jar_da", [
    ({"MUSTANG_ERWARTET": "1"}, True),     # erwartet und da
    ({}, False),                           # nicht erwartet: Skip mit Grund genügt
    ({"MUSTANG_ERWARTET": ""}, False),
    ({"MUSTANG_ERWARTET": "0"}, False),
])
def test_sonst_keine_meldung(umgebung, jar_da):
    assert jar_fehlt_obwohl_erwartet(umgebung, jar_da=jar_da) is None
