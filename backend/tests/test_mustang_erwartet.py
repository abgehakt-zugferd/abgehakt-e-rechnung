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


# -- Der Hook selbst (Unterprozess) ------------------------------------------

def _pytest_lauf(extra_env):
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    env = {k: v for k, v in os.environ.items() if k not in ("MUSTANG_ERWARTET", "MUSTANG_JAR")}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider",
         "tests/helpers/winzig_fuer_sessionstart.py"],
        cwd=backend, env=env, capture_output=True, text=True, timeout=120)


def test_sessionstart_bricht_ab_wenn_jar_erwartet_wird_und_fehlt():
    lauf = _pytest_lauf({"MUSTANG_ERWARTET": "1", "MUSTANG_JAR": "/nicht/vorhanden/Mustang.jar"})

    assert lauf.returncode == 1, lauf.stdout + lauf.stderr
    assert "MUSTANG_ERWARTET ist gesetzt" in lauf.stdout + lauf.stderr
    assert "1 passed" not in lauf.stdout


def test_sessionstart_bricht_ohne_die_variable_nicht_ab():
    lauf = _pytest_lauf({"MUSTANG_JAR": "/nicht/vorhanden/Mustang.jar"})

    assert lauf.returncode == 0, lauf.stdout + lauf.stderr
    assert "1 passed" in lauf.stdout
