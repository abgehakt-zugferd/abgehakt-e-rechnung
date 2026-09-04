"""Die Konstanten dieser App gegen `protokoll.json` im Vektorordner (abgehakt#72).

Rot, sobald das Protokoll sich bewegt hat und diese Anwendung nicht. Das ist der
ganze Abstimmungsmechanismus.
"""

import json

import pytest

from app.services.protokoll import (
    ABGELEHNT_AB_MAJOR,
    AKZEPTIERTE_FASSUNGEN,
    BEFUNDCODES,
    FELDER,
    NUTZLAST_ARTEN,
    PROTOKOLL_VERSION,
)
from app.services.uebergabebeleg import FassungUnvertraeglich, beleg_pruefen


def test_konstante_haelt_die_geltende_fassung(protokoll):
    assert PROTOKOLL_VERSION == protokoll["format_version"]


def test_akzeptierte_fassungen_stimmen_mit_dem_protokoll_ueberein(protokoll):
    assert list(AKZEPTIERTE_FASSUNGEN) == protokoll["akzeptiert"]


def test_ab_welchem_major_abgelehnt_wird_steht_im_protokoll(protokoll):
    assert ABGELEHNT_AB_MAJOR == protokoll["abgelehnt_ab_major"]


def test_befundcodes_stammen_aus_dem_protokoll(protokoll):
    assert BEFUNDCODES == frozenset(protokoll["befundcodes"])


def test_nutzlast_arten_stammen_aus_dem_protokoll(protokoll):
    assert list(NUTZLAST_ARTEN) == protokoll["nutzlast_arten"]


def _erwarteter_code(vektoren, gruppe, name):
    """Der Sollwert steht in erwartung.json, nicht in diesem Test."""
    erwartung = json.loads((vektoren / "erwartung.json").read_text(encoding="utf-8"))
    treffer = [eintrag for eintrag in erwartung[gruppe] if eintrag["name"] == name]
    assert treffer, f"{gruppe}/{name} steht nicht in erwartung.json"
    return treffer[0]["erwarteter_code"]


def test_vektoren_sind_gegen_dieselbe_fassung_gebaut(vektoren):
    erwartung = json.loads((vektoren / "erwartung.json").read_text(encoding="utf-8"))
    assert erwartung["format_version"] == PROTOKOLL_VERSION


def test_hoeherer_minor_wird_angenommen(vektoren, schluesselordner):
    """`03_hoeherer_minor` traegt 1.6 und muss durchgehen."""
    roh = (vektoren / "umschlaege" / "03_hoeherer_minor.json").read_bytes()
    befund = beleg_pruefen(roh, wurzel=schluesselordner)
    assert befund.signatur_gueltig
    assert befund.format_version.split(".")[0] == PROTOKOLL_VERSION.split(".")[0]


def test_hoeherer_major_wird_mit_befundcode_abgelehnt(vektoren, schluesselordner):
    roh = (vektoren / "ablehnung" / "major_hoeher.json").read_bytes()
    with pytest.raises(FassungUnvertraeglich) as fehler:
        beleg_pruefen(roh, wurzel=schluesselordner)
    assert fehler.value.CODE == _erwarteter_code(vektoren, "ablehnung", "major_hoeher")
    assert fehler.value.CODE in BEFUNDCODES


# Prosa im Verzeichnis: Begruendungen, keine Feldnamen. Sie gehoeren in die
# Papiere, nicht in den Vergleich.
_PROSA = {"warum", "hinweis", "nur_netto", "pfad_dokument"}


def _ohne_prosa(knoten):
    if isinstance(knoten, dict):
        return {
            schluessel: _ohne_prosa(wert)
            for schluessel, wert in knoten.items()
            if schluessel not in _PROSA
        }
    return knoten


@pytest.mark.parametrize("art", ["umschlag", "abrechnungsauftrag"])
def test_feldverzeichnis_stammt_aus_dem_protokoll(protokoll, art):
    """§ 11 UNBEKANNTES_FELD braucht ein Verzeichnis, und zwar dasselbe wie drueben.

    Bis 1.1 stand es nur als Beispiel-JSON im Papier, jede App schrieb es ab, und
    "unbekannt" war in zwei Umsetzungen etwas leicht Verschiedenes.
    """
    assert FELDER[art] == _ohne_prosa(protokoll["felder"][art])


def test_das_verzeichnis_kennt_die_verbotenen_steuerfelder(protokoll):
    """Der Auftrag traegt nur netto: steuer, brutto, steuersatz und
    steuerkategorie stehen weder unter pflicht noch unter erlaubt."""
    position = FELDER["abrechnungsauftrag"]["unterobjekte"]["gutschriften[].positionen[]"]
    gutschrift = FELDER["abrechnungsauftrag"]["unterobjekte"]["gutschriften[]"]
    for feld in ("steuer", "brutto", "steuersatz", "steuerkategorie"):
        assert feld not in position["pflicht"] + position["erlaubt"]
        assert feld not in gutschrift["pflicht"] + gutschrift["erlaubt"]


def test_die_erreichbaren_codes_dieses_empfaengers_sind_benannt(protokoll):
    """Nicht jeder Code ist fuer jeden Empfaenger erreichbar.

    Wer einen Vektor gegen einen Empfaenger misst, dem sein Code gar nicht
    begegnen kann, misst nichts. STUECKZAHLPROBE gilt in der Erloesmeldung,
    und die liest diese Anwendung nicht.
    """
    lage = protokoll["codes_je_empfaenger"]
    meine = set(lage["umschlagcodes_fuer_alle"]) | set(lage["abgehakt"]["zusaetzlich"])

    assert meine <= BEFUNDCODES
    assert lage["abgehakt"]["liest"] == ["abrechnungsauftrag"]
    assert "STUECKZAHLPROBE" in lage["abgehakt"]["nie_erreichbar"]
    assert not meine & set(lage["abgehakt"]["nie_erreichbar"])
