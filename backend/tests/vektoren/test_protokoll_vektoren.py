"""Die Konstanten dieser App gegen `protokoll.json` im Vektorordner (abgehakt#72).

Rot, sobald das Protokoll sich bewegt hat und diese Anwendung nicht. Das ist der
ganze Abstimmungsmechanismus.
"""

import hashlib
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
from app.services.uebergabe_befund import LESBARE_ARTEN, Empfangslage, beleg_beurteilen


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


class _Vorgaengerlage(Empfangslage):
    """Nur die Kette: `03_hoeherer_minor` nennt `02_nachfolger` als Vorgaenger."""

    def __init__(self, zuletzt):
        self._zuletzt = zuletzt

    def zuletzt_angenommen(self, absender):
        return self._zuletzt


def _lage_mit_vorgaenger(vektoren, name):
    """Die Lage, in der `umschlaege/<name>` bereits angenommen wurde."""
    roh = (vektoren / "umschlaege" / f"{name}.json").read_bytes()
    beleg = json.loads(roh)
    # Mit derselben Zeitregel wie der Leser selbst (protokoll.zeit, abgehakt#166):
    # wer hier anders parsed, konstruiert eine Lage, die der Leser nie erzeugt.
    from app.services.protokoll import zeit

    return _Vorgaengerlage(
        (hashlib.sha256(roh).hexdigest(), zeit(beleg["erzeugt_am"])),
    )


def test_hoeherer_minor_wird_angenommen(vektoren, schluesselordner):
    """`03_hoeherer_minor` traegt 1.8 und muss durch die Fassungsprobe kommen.

    Gemessen wird derselbe Leser wie in der Anwendung (ein Pruefpfad, abgehakt#159).
    Diese Anwendung liest die Erloesmeldung nicht, deshalb ist NUTZLASTART_UNBEKANNT
    der einzige Befund, und genau der beweist die Annahme der Fassung: In
    `beleg_beurteilen` laeuft die Fassungsprobe VOR der Artprobe und die
    Signaturprobe VOR der Artprobe am Ende. Waere der minor abgelehnt, stünde
    FASSUNG_UNVERTRAEGLICH da. Der Umschlag geht an einen anderen Empfaenger
    (feiyr-konto an tantiemen-app) und bekommt deshalb dessen Namen gereicht.
    """
    roh = (vektoren / "umschlaege" / "03_hoeherer_minor.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _lage_mit_vorgaenger(vektoren, "02_nachfolger"),
        schluessel_wurzel=schluesselordner, eigener_name="tantiemen-app",
    )

    assert [f.code for f in urteil.feststellungen] == ["NUTZLASTART_UNBEKANNT"]


def test_hoeherer_major_wird_mit_befundcode_abgelehnt(vektoren, schluesselordner):
    roh = (vektoren / "ablehnung" / "major_hoeher.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, Empfangslage(), schluessel_wurzel=schluesselordner,
        eigener_name="tantiemen-app",
    )

    assert [f.code for f in urteil.feststellungen] == [
        _erwarteter_code(vektoren, "ablehnung", "major_hoeher")
    ]
    assert urteil.feststellungen[0].code in BEFUNDCODES


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

    Seit 1.7 nennt das Protokoll abgehakt mit den beiden neuen Arten; der
    rechnungsauftrag wird seit Teil 1a gelesen (seine Grundregeln), der
    aufstellungsauftrag wartet weiter auf seine Freigabe, gelesen wird die
    Teilmenge (LESBARE_ARTEN). Die Differenz ist damit benannt und gesperrt:
    Waechst das Protokoll um eine Art, die dieser Empfaenger still schluckt,
    wird dieser Test rot - genauso wie beim Bau, der LESBARE_ARTEN erweitert
    und ihn mitzieht.
    """
    lage = protokoll["codes_je_empfaenger"]
    meine = set(lage["umschlagcodes_fuer_alle"]) | set(lage["abgehakt"]["zusaetzlich"])

    assert meine <= BEFUNDCODES
    assert set(LESBARE_ARTEN) <= set(lage["abgehakt"]["liest"])
    assert set(lage["abgehakt"]["liest"]) - set(LESBARE_ARTEN) == {
        "aufstellungsauftrag",
    }
    assert "STUECKZAHLPROBE" in lage["abgehakt"]["nie_erreichbar"]
    assert not meine & set(lage["abgehakt"]["nie_erreichbar"])
