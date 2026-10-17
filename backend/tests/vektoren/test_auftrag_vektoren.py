"""Der Leser gegen die Formatvektoren (abgehakt#22).

Die Vektoren sind Dateien, kein Modul. Gemessen wird gegen die Bytes und gegen
die Sollwerte in `erwartung.json`; in diesem Test steht kein abgeschriebener
Befundcode.

Zwei Dinge, die man beim Lesen sonst fuer Nachlaessigkeit haelt:

* Die Umschlagvektoren sind fuer einen ANDEREN Empfaenger gebaut (feiyr-konto
  an tantiemen-app). Die Umschlagregeln sind aber dieselben, egal wer liest -
  deshalb bekommt der Leser dort den Namen des gemeinten Empfaengers gereicht.
  Mit dem eigenen Namen faende jeder dieser Faelle EMPFAENGER_FREMD, und der
  Lauf haette nur gemessen, dass die Post nicht an uns ging.
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

from app.services.abrechnungsauftrag_wirkung import WirkungFehler, entwuerfe_anlegen
from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen

# Die drei Vektoren, deren Regel in der Nutzlast der Erloesmeldung sitzt.
NUR_FUER_DEN_ERLOESLESER = {"unbekanntes_feld", "pflichtfeld_fehlt", "stueckzahlprobe"}

# Die Auftragsfaelle, die abgelehnt werden. `01_gueltig` steht daneben, nicht hier.
ABGELEHNTE_AUFTRAEGE = (
    "summe_stimmt_nicht",
    "partner_id_unbekannt",
    "unbekanntes_feld",
    "pflichtfeld_fehlt",
    "wert_unbrauchbar",
)

PARTNER_DES_PROBEBESTANDS = (
    "3f5b1c80-0000-4000-8000-00000000000a",
    "3f5b1c80-0000-4000-8000-00000000000b",
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


def _erwartung(vektoren) -> dict:
    roh = json.loads((vektoren / "erwartung.json").read_text(encoding="utf-8"))
    return {gruppe: {e["name"]: e for e in eintraege}
            for gruppe, eintraege in roh.items() if isinstance(eintraege, list)}


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


def _namen(vektoren, gruppe):
    return sorted(_erwartung(vektoren)[gruppe])


def test_jeder_ablehnungsvektor_ist_gemessen_oder_begruendet_ausgenommen(vektoren):
    """Kein stilles Weglassen: was nicht gemessen wird, steht in der Liste oben."""
    dateien = {p.stem for p in (vektoren / "ablehnung").glob("*.json")}
    assert dateien == set(_namen(vektoren, "ablehnung"))
    assert NUR_FUER_DEN_ERLOESLESER < dateien


@pytest.mark.parametrize("name", [
    "beleg_unlesbar", "nutzlast_hash_falsch", "signatur_ungueltig", "empfaenger_fremd",
    "major_hoeher", "kette_springt", "kette_beginnt_neu", "erzeugt_am_rueckwaerts",
    "schluessel_unbekannt", "nutzlastart_unbekannt", "beleg_id_widerspruch",
])
def test_ablehnungsvektor_trifft_seinen_befundcode(vektoren, schluesselordner, name):
    erwartet = _erwartung(vektoren)["ablehnung"][name]["erwarteter_code"]
    roh = (vektoren / "ablehnung" / f"{name}.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _kettenanfang(vektoren),
        schluessel_wurzel=schluesselordner,
        eigener_name="tantiemen-app",
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
        eigener_name="tantiemen-app",
    )

    assert not urteil.angenommen
    assert [f.code for f in urteil.feststellungen] == ["NUTZLASTART_UNBEKANNT"]


@pytest.mark.parametrize("gruppe", ["rechnungsauftraege", "aufstellungen"])
def test_die_neuen_arten_werden_noch_nicht_gelesen(vektoren, schluesselordner, gruppe):
    """1.7 kennt rechnungsauftrag und aufstellungsauftrag (§§ 8a, 8b); dieser
    Empfaenger liest sie noch nicht, der Bau wartet auf eine Freigabe.

    Gemessen wird je der Kettenanfang der Gruppe: ein gueltig signierter,
    richtig an diesen Empfaenger adressierter Beleg. Er kommt durch jede
    Umschlagprobe - Fassung, Hash, Signatur, Kette - und faellt genau an der
    Artprobe, nicht frueher: GENAU EIN Befund beweist, dass nichts anderes
    ihn abgewiesen hat. Die Wirkung verweigert fuer abgelehnte Belege, es
    entsteht kein Entwurf; gemessen am ersten Haken von entwuerfe_anlegen.

    Die beiden Gruppen sind damit NICHT als Annahme-Tests eingesammelt; ihre
    uebrigen Faelle kommen mit dem Bau.
    """
    roh = (vektoren / gruppe / "01_gueltig.json").read_bytes()

    urteil = beleg_beurteilen(roh, Empfangslage(), schluessel_wurzel=schluesselordner)

    assert not urteil.angenommen
    assert [f.code for f in urteil.feststellungen] == ["NUTZLASTART_UNBEKANNT"]
    assert urteil.nutzlast_art == json.loads(roh)["nutzlast_art"]
    with pytest.raises(WirkungFehler):
        entwuerfe_anlegen(None, urteil)


def test_derselbe_beleg_noch_einmal_ist_keine_ablehnung(vektoren, schluesselordner):
    """`beleg_id_doppelt` ist byteweise `01_kettenanfang` - der Fall, der am
    haeufigsten falsch gebaut wird."""
    erwartet = _erwartung(vektoren)["ablehnung"]["beleg_id_doppelt"]["erwarteter_code"]
    assert erwartet == "KEINE_ABLEHNUNG"
    roh = (vektoren / "ablehnung" / "beleg_id_doppelt.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _kettenanfang(vektoren),
        schluessel_wurzel=schluesselordner,
        eigener_name="tantiemen-app",
    )

    assert urteil.angenommen
    assert urteil.bereits_verarbeitet
    assert urteil.feststellungen == ()


# Die Umschlaege sind Erloesmeldungen feiyr-konto an tantiemen-app; ihre
# Sollwerte in erwartung.json sind die Hashes, kein erwarteter Code.
UMSCHLAEGE = ("01_kettenanfang", "02_nachfolger", "03_hoeherer_minor")


class _Zweitlesung(Empfangslage):
    """Die Lage, in der dieser Beleg bereits angenommen und gewirkt hat."""

    def __init__(self, roh):
        beleg = json.loads(roh)
        # Mit derselben Zeitregel wie der Leser selbst (protokoll.zeit, abgehakt#166):
        # wer hier anders parsed, konstruiert eine Lage, die der Leser nie erzeugt.
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
    dateien = {p.stem for p in (vektoren / "umschlaege").glob("*.json")}
    assert dateien == set(_namen(vektoren, "umschlaege"))
    assert dateien == set(UMSCHLAEGE)


@pytest.mark.parametrize("name", UMSCHLAEGE)
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
    eintrag = _erwartung(vektoren)["umschlaege"][name]
    roh = (vektoren / "umschlaege" / f"{name}.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _Zweitlesung(roh), schluessel_wurzel=schluesselordner,
        eigener_name="tantiemen-app",
    )

    assert urteil.angenommen
    assert urteil.bereits_verarbeitet
    assert urteil.feststellungen == ()
    assert urteil.beleg_sha256 == eintrag["beleg_sha256"]
    # Der Hash der Nutzlast steht im Beleg und in erwartung.json. Dass er zur
    # Nutzlast stimmt, hat der Leser eben geprueft: NUTZLAST_HASH_FALSCH
    # waere vor dem Riegel gekommen.
    assert json.loads(roh)["nutzlast_sha256"] == eintrag["nutzlast_sha256"]


def test_der_gueltige_auftrag_wird_angenommen(vektoren, schluesselordner):
    """Die Zahlen stammen aus der von Hand hergeleiteten Solltabelle des
    Probebestands, nicht aus einer zweiten Rechnung dieses Programms."""
    roh = (vektoren / "auftraege" / "01_gueltig.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, Lage(partner=PARTNER_DES_PROBEBESTANDS), schluessel_wurzel=schluesselordner,
    )

    assert urteil.angenommen, [f"{f.code} {f.pfad}" for f in urteil.feststellungen]
    assert urteil.zahl_gutschriften == 2
    assert str(urteil.summe_netto) == "440.10"
    assert urteil.abrechnungsquartal == "2026-Q2"


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
    dateien = {p.stem for p in (vektoren / "auftraege").glob("*.json")}
    assert dateien == set(_namen(vektoren, "auftraege"))
    assert dateien == {"01_gueltig"} | set(ABGELEHNTE_AUFTRAEGE)


@pytest.mark.parametrize("name", ABGELEHNTE_AUFTRAEGE)
def test_auftragsvektor_trifft_seinen_befundcode(vektoren, schluesselordner, name):
    erwartet = _erwartung(vektoren)["auftraege"][name]["erwarteter_code"]
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
