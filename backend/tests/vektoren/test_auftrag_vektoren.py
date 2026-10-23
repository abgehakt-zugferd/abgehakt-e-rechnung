"""Der Leser gegen die Formatvektoren (abgehakt#22, Parametrisierung #217).

Die Vektoren sind Dateien, kein Modul. Gemessen wird gegen die Bytes und gegen
die Sollwerte in `erwartung.json`; in diesem Test steht kein abgeschriebener
Befundcode. Die Falllisten kommen aus erwartung.json.

Zwei Dinge, die man beim Lesen sonst fuer Nachlaessigkeit haelt:

* Die Umschlagvektoren sind fuer einen anderen Empfaenger gebaut. Die
  Umschlagregeln sind dieselben, egal wer liest - deshalb bekommt der Leser
  dort den Namen des gemeinten Empfaengers gereicht. Mit dem eigenen Namen
  faende jeder dieser Faelle EMPFAENGER_FREMD, und der Lauf haette nur
  gemessen, dass die Post nicht an uns ging.
* Drei Vektoren pruefen Regeln der `erloesmeldung` (ein unbekanntes Feld in
  ihrer Nutzlast, ein fehlendes Pflichtfeld, die Stueckzahlprobe). Diese
  Anwendung liest die Nutzlastart gar nicht; sie lehnt frueher ab. Sie werden
  deshalb NICHT gegen ihren erwarteten Code gemessen, sondern nur daraufhin,
  dass hier nichts davon angenommen wird. Alles andere waere gruen aus dem
  falschen Grund.
"""

import hashlib
import json

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
from tests.helpers.formatvektoren import vektorordner
from tests.vektoren.erwartung_lesen import (
    eintraege,
    erwarteter_code,
    lagebedarf,
    namen_beim_sammeln,
    pruefe_vollstaendigkeit,
)

# Die drei Vektoren, deren Regel in der Nutzlast der Erloesmeldung sitzt.
NUR_FUER_DEN_ERLOESLESER = frozenset({
    "unbekanntes_feld", "pflichtfeld_fehlt", "stueckzahlprobe",
})

PARTNER_DES_PROBEBESTANDS = (
    "3f5b1c80-0000-4000-8000-00000000000a",
    "3f5b1c80-0000-4000-8000-00000000000b",
)

# Empfaengername der Umschlagvektoren: Parameter, nicht der Fall (vektoren/README).
_UMSCHLAG_EMPFAENGER = "tantiemen-app"


def _namen_ablehnung_mit_befund() -> list[str]:
    ordner = vektorordner()
    if ordner is None:
        return []
    namen = []
    for name, eintrag in eintraege(ordner / "vektoren", "ablehnung").items():
        if name in NUR_FUER_DEN_ERLOESLESER:
            continue
        if eintrag.get("erwarteter_code") == "KEINE_ABLEHNUNG":
            continue
        namen.append(name)
    return sorted(namen)


def _namen_auftraege_abgelehnt() -> list[str]:
    ordner = vektorordner()
    if ordner is None:
        return []
    return sorted(
        name
        for name, eintrag in eintraege(ordner / "vektoren", "auftraege").items()
        if eintrag.get("erwarteter_code") not in (None, "KEINE_ABLEHNUNG")
    )


class Lage(Empfangslage):
    def __init__(self, zuletzt=None, kennungen=None, partner=()):
        self._zuletzt = zuletzt
        self._kennungen = kennungen or {}
        self._partner = partner

    def zuletzt_angenommen(self, absender):
        return self._zuletzt

    def sha_zu_beleg_id(self, beleg_id):
        return self._kennungen.get(beleg_id)

    def partner_bekannt(self, partner_id):
        return partner_id in self._partner


def _kettenanfang(vektoren):
    """Die Lage, in der `umschlaege/01_kettenanfang` bereits angenommen wurde."""
    roh = (vektoren / "umschlaege" / "01_kettenanfang.json").read_bytes()
    beleg = json.loads(roh)
    # Mit derselben Zeitregel wie der Leser selbst (protokoll.zeit, abgehakt#166):
    # wer hier anders parsed, konstruiert eine Lage, die der Leser nie erzeugt.
    from app.services.protokoll import zeit

    return Lage(
        zuletzt=(hashlib.sha256(roh).hexdigest(), zeit(beleg["erzeugt_am"])),
        kennungen={beleg["beleg_id"]: hashlib.sha256(roh).hexdigest()},
    )


def test_alle_voraussetzungen_der_auftragsgruppen_sind_unterstuetzt(vektoren):
    """Neue Voraussetzungswortlaute muessen hier angebunden werden, nicht still."""
    for gruppe in ("auftraege", "rechnungsauftraege", "aufstellungen"):
        for eintrag in eintraege(vektoren, gruppe).values():
            lagebedarf(eintrag.get("voraussetzung"))


def test_jeder_ablehnungsvektor_ist_gemessen_oder_begruendet_ausgenommen(vektoren):
    """Kein stilles Weglassen: was nicht gemessen wird, steht in der Liste oben."""
    pruefe_vollstaendigkeit(vektoren, "ablehnung")
    dateien = {p.stem for p in (vektoren / "ablehnung").glob("*.json")}
    assert NUR_FUER_DEN_ERLOESLESER < dateien


@pytest.mark.parametrize("name", _namen_ablehnung_mit_befund())
def test_ablehnungsvektor_trifft_seinen_befundcode(vektoren, schluesselordner, name):
    erwartet = erwarteter_code(eintraege(vektoren, "ablehnung")[name])
    roh = (vektoren / "ablehnung" / f"{name}.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _kettenanfang(vektoren),
        schluessel_wurzel=schluesselordner,
        eigener_name=_UMSCHLAG_EMPFAENGER,
    )

    assert not urteil.angenommen
    assert [f.code for f in urteil.feststellungen] == [erwartet]
    assert urteil.beleg_sha256 == hashlib.sha256(roh).hexdigest()


@pytest.mark.parametrize("name", sorted(NUR_FUER_DEN_ERLOESLESER))
def test_erloesmeldungen_werden_hier_gar_nicht_erst_gelesen(vektoren, schluesselordner, name):
    roh = (vektoren / "ablehnung" / f"{name}.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _kettenanfang(vektoren),
        schluessel_wurzel=schluesselordner,
        eigener_name=_UMSCHLAG_EMPFAENGER,
    )

    assert not urteil.angenommen
    assert [f.code for f in urteil.feststellungen] == ["NUTZLASTART_UNBEKANNT"]


def test_derselbe_beleg_noch_einmal_ist_keine_ablehnung(vektoren, schluesselordner):
    """`beleg_id_doppelt` ist byteweise `01_kettenanfang` - der Fall, der am
    haeufigsten falsch gebaut wird."""
    erwartet = erwarteter_code(eintraege(vektoren, "ablehnung")["beleg_id_doppelt"])
    assert erwartet == "KEINE_ABLEHNUNG"
    roh = (vektoren / "ablehnung" / "beleg_id_doppelt.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _kettenanfang(vektoren),
        schluessel_wurzel=schluesselordner,
        eigener_name=_UMSCHLAG_EMPFAENGER,
    )

    assert urteil.angenommen
    assert urteil.bereits_verarbeitet
    assert urteil.feststellungen == ()


class _Zweitlesung(Empfangslage):
    """Die Lage, in der dieser Beleg bereits angenommen und gewirkt hat."""

    def __init__(self, roh):
        beleg = json.loads(roh)
        # Mit derselben Zeitregel wie der Leser selbst (protokoll.zeit, abgehakt#166).
        from app.services.protokoll import zeit

        self._sha = hashlib.sha256(roh).hexdigest()
        self._kennungen = {beleg["beleg_id"]: self._sha}
        self._zuletzt = (self._sha, zeit(beleg["erzeugt_am"]))

    def zuletzt_angenommen(self, absender):
        return self._zuletzt

    def sha_zu_beleg_id(self, beleg_id):
        return self._kennungen.get(beleg_id)


def test_jeder_umschlagsvektor_ist_gemessen(vektoren):
    """Kein stilles Weglassen: jede Datei im Ordner kommt in einem Test vor."""
    pruefe_vollstaendigkeit(vektoren, "umschlaege")


@pytest.mark.parametrize("name", namen_beim_sammeln("umschlaege"))
def test_umschlagsvektor_wird_angenommen(vektoren, schluesselordner, name):
    """erwartung.json zu `umschlaege`: muss angenommen werden, Hashes wie erwartet.

    Die Nutzlast dieser Belege ist eine Erloesmeldung, und die liest dieser
    Empfaenger nicht - bis zur Artprobe kommt ein frischer Lauf also nie.
    Die Annahme ist deshalb als Zweitlesung gemessen (§ 11 letzte Zeile:
    zweimal eingelesen heisst einmal gewirkt, dieselbe Quittung noch einmal).
    Der Idempotenzriegel sitzt im Pruefpfad hinter Bytes, Umschlag, Fassung,
    Nutzlast-Hash und Signatur: Keine Feststellung entsteht dort, ohne dass
    jede dieser Proben zuvor gruen war. Die Kette misst der frische Lauf von
    `03_hoeherer_minor` mit Vorgaengerlage (test_protokoll_vektoren.py).
    """
    eintrag = eintraege(vektoren, "umschlaege")[name]
    roh = (vektoren / "umschlaege" / f"{name}.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _Zweitlesung(roh), schluessel_wurzel=schluesselordner,
        eigener_name=_UMSCHLAG_EMPFAENGER,
    )

    assert urteil.angenommen
    assert urteil.bereits_verarbeitet
    assert urteil.feststellungen == ()
    assert urteil.beleg_sha256 == eintrag["beleg_sha256"]
    assert json.loads(roh)["nutzlast_sha256"] == eintrag["nutzlast_sha256"]


def test_der_gueltige_auftrag_wird_angenommen(vektoren, schluesselordner):
    """Die Zahlen stammen aus der von Hand hergeleiteten Solltabelle des
    Probebestands, nicht aus einer zweiten Rechnung dieses Programms."""
    eintrag = eintraege(vektoren, "auftraege")["01_gueltig"]
    lagebedarf(eintrag.get("voraussetzung"))
    roh = (vektoren / "auftraege" / "01_gueltig.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, Lage(partner=PARTNER_DES_PROBEBESTANDS), schluessel_wurzel=schluesselordner,
    )

    assert urteil.angenommen, [f"{f.code} {f.pfad}" for f in urteil.feststellungen]
    assert urteil.zeitraum == "2026-Q2"
    assert urteil.summe == "440,10"
    assert erwarteter_code(eintrag) == "KEINE_ABLEHNUNG"
    assert urteil.beleg_sha256 == eintrag["beleg_sha256"]


def _lage_nach_dem_gueltigen(vektoren, partner=PARTNER_DES_PROBEBESTANDS):
    roh = (vektoren / "auftraege" / "01_gueltig.json").read_bytes()
    beleg = json.loads(roh)
    from app.services.protokoll import zeit

    return Lage(
        zuletzt=(hashlib.sha256(roh).hexdigest(), zeit(beleg["erzeugt_am"])),
        kennungen={beleg["beleg_id"]: hashlib.sha256(roh).hexdigest()},
        partner=partner,
    )


def test_jeder_auftragsvektor_ist_gemessen(vektoren):
    """Kein stilles Weglassen: jede Datei im Ordner kommt in einem Test vor."""
    pruefe_vollstaendigkeit(vektoren, "auftraege")


@pytest.mark.parametrize("name", _namen_auftraege_abgelehnt())
def test_auftragsvektor_trifft_seinen_befundcode(vektoren, schluesselordner, name):
    eintrag = eintraege(vektoren, "auftraege")[name]
    lagebedarf(eintrag.get("voraussetzung"))
    erwartet = erwarteter_code(eintrag)
    roh = (vektoren / "auftraege" / f"{name}.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _lage_nach_dem_gueltigen(vektoren), schluessel_wurzel=schluesselordner,
    )

    assert not urteil.angenommen
    assert [f.code for f in urteil.feststellungen] == [erwartet]


def test_der_gueltige_auftrag_braucht_beide_partner_im_stamm(vektoren, schluesselordner):
    """Ohne Kunden im Stamm faellt derselbe Beleg - die Voraussetzung, die
    erwartung.json fuer `01_gueltig` nennt, ist wirklich eine. Beide Gutschriften
    nennen je einen Beteiligten, und § 10 verlangt JE Grund einen Befund: Der
    Leser nennt beide Stellen, nicht nur die zuerst gelesene."""
    roh = (vektoren / "auftraege" / "01_gueltig.json").read_bytes()

    urteil = beleg_beurteilen(roh, Lage(partner=()), schluessel_wurzel=schluesselordner)

    assert [f.code for f in urteil.feststellungen] == [
        "PARTNER_ID_UNBEKANNT", "PARTNER_ID_UNBEKANNT",
    ]
    assert {f.pfad for f in urteil.feststellungen} == {
        "$.nutzlast.gutschriften[0].beteiligter.partner_id",
        "$.nutzlast.gutschriften[1].beteiligter.partner_id",
    }
