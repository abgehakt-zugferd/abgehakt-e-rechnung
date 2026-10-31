"""Name der Test-Datenbank und je Prozess abgeleitete Clusternamen.

Parallele pytest-Prozesse (Mutationspruefung) teilen sich einen Postgres-Cluster.
Ein fester Datenbankname laesst sie einander die DB loeschen; der Name geht
ausserdem per f-String in SQL, also muss er ein sicherer Bezeichner sein.
"""
import pytest

from tests.helpers.testdb import STANDARD_NAME, datenbankname, je_prozess


def test_standard_ohne_umgebung():
    assert datenbankname({}) == "abgehakt_test"
    assert STANDARD_NAME == "abgehakt_test"


def test_umgebungsvariable_setzt_den_namen():
    assert datenbankname({"ABGEHAKT_TEST_DB": "mein_lauf"}) == "mein_lauf"


def test_je_prozess_haengt_die_pid_an():
    assert datenbankname({"ABGEHAKT_TEST_DB_JE_PROZESS": "1"}, pid=4711) == "abgehakt_test_4711"


def test_je_prozess_kombiniert_mit_eigenem_namen():
    umgebung = {"ABGEHAKT_TEST_DB": "mein_lauf", "ABGEHAKT_TEST_DB_JE_PROZESS": "1"}
    assert datenbankname(umgebung, pid=7) == "mein_lauf_7"


@pytest.mark.parametrize("wert", ["0", "", "nein"])
def test_je_prozess_nur_bei_eins(wert):
    assert datenbankname({"ABGEHAKT_TEST_DB_JE_PROZESS": wert}, pid=9) == "abgehakt_test"


@pytest.mark.parametrize("boese", [
    "x; DROP DATABASE postgres", 'a"b', "mit leer", "Gross", "1beginnt_mit_ziffer",
    "a-b", "x" * 64,
])
def test_ungueltiger_name_scheitert_laut(boese):
    with pytest.raises(ValueError, match="ABGEHAKT_TEST_DB"):
        datenbankname({"ABGEHAKT_TEST_DB": boese})


def test_leerer_name_scheitert_laut():
    with pytest.raises(ValueError, match="ABGEHAKT_TEST_DB"):
        datenbankname({"ABGEHAKT_TEST_DB": ""})


def test_zu_langer_name_mit_pid_scheitert_laut():
    # 60 Zeichen sind allein gueltig, mit "_<pid>" ueber der Grenze von 63.
    umgebung = {"ABGEHAKT_TEST_DB": "a" * 60, "ABGEHAKT_TEST_DB_JE_PROZESS": "1"}
    with pytest.raises(ValueError, match="ABGEHAKT_TEST_DB"):
        datenbankname(umgebung, pid=123456)


def test_je_prozess_fuer_beliebige_namen_ohne_schalter_unveraendert():
    assert je_prozess("abgehakt_test_owner", {}) == "abgehakt_test_owner"


def test_je_prozess_fuer_beliebige_namen_mit_schalter():
    assert je_prozess("abgehakt_test_owner", {"ABGEHAKT_TEST_DB_JE_PROZESS": "1"}, pid=5) == "abgehakt_test_owner_5"
