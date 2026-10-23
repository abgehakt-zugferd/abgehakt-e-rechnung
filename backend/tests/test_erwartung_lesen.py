"""Die gemeinsame Lesefunktion fuer Formatvektor-Erwartungen (abgehakt#217).

Gemessen wird gegen eine Kopie unter tmp_path - der echte Vektorordner bleibt
unangetastet. Ohne lesbare Erwartung, bei Luecken zwischen Datei und Eintrag
oder bei unbekannter Voraussetzung muss es rot werden, nie still.
"""

import json
from pathlib import Path

import pytest

from tests.vektoren.erwartung_lesen import (
    eintraege,
    lagebedarf,
    namen,
    pruefe_vollstaendigkeit,
    roh_laden,
)


def _schreibe_erwartung(ordner: Path, gruppe: str, faelle: list) -> Path:
    vektoren = ordner / "vektoren"
    vektoren.mkdir(parents=True)
    (vektoren / "erwartung.json").write_text(
        json.dumps({"format_version": "1.7", gruppe: faelle}),
        encoding="utf-8",
    )
    return vektoren


def test_roh_laden_verlangt_lesbare_erwartung(tmp_path):
    vektoren = tmp_path / "vektoren"
    vektoren.mkdir()
    with pytest.raises(AssertionError, match="keine lesbare Erwartung"):
        roh_laden(vektoren)


def test_eintrag_ohne_name_ist_unlesbar(tmp_path):
    vektoren = _schreibe_erwartung(
        tmp_path, "auftraege", [{"erwarteter_code": "KEINE_ABLEHNUNG"}],
    )
    with pytest.raises(AssertionError, match="keine lesbare Erwartung"):
        eintraege(vektoren, "auftraege")


def test_eintraege_und_namen_aus_gruppe(tmp_path):
    vektoren = _schreibe_erwartung(
        tmp_path,
        "auftraege",
        [
            {"name": "b_fall", "erwarteter_code": "SUMME_STIMMT_NICHT"},
            {"name": "a_fall", "erwarteter_code": "KEINE_ABLEHNUNG"},
        ],
    )

    gelesen = eintraege(vektoren, "auftraege")

    assert set(gelesen) == {"a_fall", "b_fall"}
    assert namen(vektoren, "auftraege") == ["a_fall", "b_fall"]
    assert gelesen["a_fall"]["erwarteter_code"] == "KEINE_ABLEHNUNG"


def test_vollstaendigkeit_rot_wenn_eintrag_fehlt(tmp_path):
    vektoren = _schreibe_erwartung(
        tmp_path, "auftraege", [{"name": "nur_json", "erwarteter_code": "X"}],
    )
    gruppe = vektoren / "auftraege"
    gruppe.mkdir()
    (gruppe / "nur_json.json").write_text("{}", encoding="utf-8")
    (gruppe / "ohne_eintrag.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AssertionError, match="vollstaendig"):
        pruefe_vollstaendigkeit(vektoren, "auftraege")


def test_vollstaendigkeit_rot_wenn_datei_fehlt(tmp_path):
    vektoren = _schreibe_erwartung(
        tmp_path,
        "auftraege",
        [
            {"name": "mit_datei", "erwarteter_code": "X"},
            {"name": "ohne_datei", "erwarteter_code": "Y"},
        ],
    )
    gruppe = vektoren / "auftraege"
    gruppe.mkdir()
    (gruppe / "mit_datei.json").write_text("{}", encoding="utf-8")

    with pytest.raises(AssertionError, match="vollstaendig"):
        pruefe_vollstaendigkeit(vektoren, "auftraege")


def test_vollstaendigkeit_gruen_bei_gleicher_menge(tmp_path):
    vektoren = _schreibe_erwartung(
        tmp_path, "auftraege", [{"name": "allein", "erwarteter_code": "X"}],
    )
    gruppe = vektoren / "auftraege"
    gruppe.mkdir()
    (gruppe / "allein.json").write_text("{}", encoding="utf-8")

    pruefe_vollstaendigkeit(vektoren, "auftraege")


def test_unbekannte_voraussetzung_scheitert_mit_meldung():
    with pytest.raises(
        AssertionError,
        match="Voraussetzung nicht unterstützt: Schluessel auf dem Mond",
    ):
        lagebedarf("Schluessel auf dem Mond")


def test_bekannte_voraussetzung_liefert_lagebedarf():
    bedarf = lagebedarf(
        "01_gueltig ist angenommen; gemessen wird dieser Beleg als naechster."
    )
    assert bedarf.nach_01 is True
    assert bedarf.mit_dokument is False


def test_fehlende_voraussetzung_nutzt_vorgabe_nach_01():
    bedarf = lagebedarf(None)
    assert bedarf.nach_01 is True
    assert bedarf.mit_dokument is False
