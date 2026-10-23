"""Formproben des Uebergabe-Lesers ohne Nachsicht fuer Zeilenenden (#210).

re.match mit einem Muster auf $ trifft auch vor einem abschliessenden \\n;
fullmatch nicht. Jede Form wird ueber die oeffentliche Grenze geprueft
(beleg_beurteilen bzw. schluessel_laden), nicht an privaten Helfern.
"""

import json
from datetime import datetime, timezone

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
from app.services.uebergabe_schluessel import SchluesselUnbekannt, schluessel_laden
from app.services.uebergabebeleg import VERFAHREN, kanonisch
from tests.helpers.uebergabe import (
    ABSENDER_TANTIEMEN,
    PARTNER_A,
    SCHLUESSEL_ID,
    aufstellungsauftrag,
    auftrag,
    beiblatt,
    beiblatt_ablegen,
    beleg,
    probe_anlagen,
    rechnungsauftrag,
    schluesselpaar,
)

SCHLUESSEL_IM_BELEG = "plattform:2026-02:kanal-a:x1"
ERZEUGT_AM = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)


class _Lage(Empfangslage):
    def __init__(self, dokumente=None, partner=(), anlagen=None):
        self._dokumente = dokumente or {}
        self._partner = partner if partner else (PARTNER_A,)
        self._anlagen = anlagen if anlagen is not None else probe_anlagen()

    def dokument_zu_auftragsschluessel(self, schluessel):
        return self._dokumente.get(schluessel)

    def partner_bekannt(self, partner_id):
        return partner_id in self._partner

    def anlagen_bytes(self, sha256):
        return self._anlagen.get(sha256)


@pytest.fixture
def schluessel(tmp_path):
    return schluesselpaar(tmp_path)


def _urteil(schluessel, nutzlast, lage=None, **umschlag):
    roh = beleg(schluessel[0], nutzlast, **umschlag)
    return beleg_beurteilen(
        roh, lage or _Lage(), schluessel_wurzel=schluessel[1],
    )


def _befunde(urteil):
    return [(f.code, f.pfad) for f in urteil.feststellungen]


def _geld_mit_zeilenende(nutzlast):
    nutzlast["gutschriften"][0]["positionen"][0]["netto"] = "174.33\n"
    return nutzlast


def _satz_mit_zeilenende(nutzlast):
    nutzlast["gutschriften"][0]["positionen"][0]["herleitung"]["satz"] = "25.00\n"
    return nutzlast


def _auftragsschluessel_mit_zeilenende(nutzlast):
    nutzlast["auftragsschluessel"] = SCHLUESSEL_IM_BELEG + "\n"
    return nutzlast


def _sha256_grundlage_mit_zeilenende(nutzlast):
    nutzlast["grundlagen"][0]["beleg_sha256"] = "1a" * 32 + "\n"
    return nutzlast


def _monat_mit_zeilenende(nutzlast):
    nutzlast["grundlagen"][0]["leistungsperiode"] = "2026-02\n"
    return nutzlast


def _waehrung_mit_zeilenende(nutzlast):
    nutzlast["waehrung"] = "USD\n"
    return nutzlast


def _kurs_mit_zeilenende(nutzlast):
    nutzlast["umrechnung"]["kurs"] = "0.8533\n"
    return nutzlast


def _zahlungsnummer_mit_zeilenende(nutzlast):
    nutzlast["zahlung"]["zahlungsnummer"] = "100000000000001\n"
    return nutzlast


def _anlage_sha256_mit_zeilenende(nutzlast):
    nutzlast["anlagen"][0]["sha256"] = nutzlast["anlagen"][0]["sha256"] + "\n"
    return nutzlast


@pytest.mark.parametrize("name,builder,art,code,pfad", [
    ("geld", _geld_mit_zeilenende, "abrechnungsauftrag",
     "WERT_UNBRAUCHBAR", "$.nutzlast.gutschriften[0].positionen[0].netto"),
    ("satz", _satz_mit_zeilenende, "abrechnungsauftrag",
     "WERT_UNBRAUCHBAR",
     "$.nutzlast.gutschriften[0].positionen[0].herleitung.satz"),
    ("auftragsschluessel", _auftragsschluessel_mit_zeilenende, "rechnungsauftrag",
     "WERT_UNBRAUCHBAR", "$.nutzlast.auftragsschluessel"),
    ("sha256_grundlage", _sha256_grundlage_mit_zeilenende, "rechnungsauftrag",
     "WERT_UNBRAUCHBAR", "$.nutzlast.grundlagen[0].beleg_sha256"),
    ("monat", _monat_mit_zeilenende, "rechnungsauftrag",
     "WERT_UNBRAUCHBAR", "$.nutzlast.grundlagen[0].leistungsperiode"),
    ("waehrung", _waehrung_mit_zeilenende, "aufstellungsauftrag",
     "WERT_UNBRAUCHBAR", "$.nutzlast.waehrung"),
    ("kurs", _kurs_mit_zeilenende, "aufstellungsauftrag",
     "WERT_UNBRAUCHBAR", "$.nutzlast.umrechnung.kurs"),
    ("zahlungsnummer", _zahlungsnummer_mit_zeilenende, "aufstellungsauftrag",
     "WERT_UNBRAUCHBAR", "$.nutzlast.zahlung.zahlungsnummer"),
    ("sha256_anlage", _anlage_sha256_mit_zeilenende, "aufstellungsauftrag",
     "WERT_UNBRAUCHBAR", "$.nutzlast.anlagen[0].sha256"),
])
def test_form_lehnt_angehaengtes_zeilenende_ab(schluessel, name, builder, art, code, pfad):
    """Je Form: der bisher gueltige Wert mit angehaengtem \\n ist unbrauchbar."""
    if art == "abrechnungsauftrag":
        nutzlast = builder(auftrag())
    elif art == "rechnungsauftrag":
        nutzlast = builder(rechnungsauftrag())
    else:
        nutzlast = builder(aufstellungsauftrag())

    urteil = _urteil(schluessel, nutzlast, nutzlast_art=art)

    assert (code, pfad) in _befunde(urteil), _befunde(urteil)
    assert not urteil.angenommen


def test_erzeugt_am_mit_zeilenende_ist_unbrauchbar(schluessel):
    """ZEITFORM in protokoll.zeit: auch erzeugt_am duldet kein abschliessendes \\n."""
    urteil = _urteil(
        schluessel, auftrag(), erzeugt_am="2026-09-03T11:00:00Z\n",
    )

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", "$.erzeugt_am")]


def test_kennung_mit_zeilenende_hat_keinen_schluessel(schluessel):
    """_KENNUNG am Schluessellader: absender mit \\n ist keine Kennung."""
    _, wurzel = schluessel

    with pytest.raises(SchluesselUnbekannt, match="keine Schluesselkennung"):
        schluessel_laden(ABSENDER_TANTIEMEN + "\n", SCHLUESSEL_ID, ERZEUGT_AM, wurzel=wurzel)


def test_auftragsschluessel_mit_zeilenende_umgeht_schon_gerechnet_nicht(schluessel):
    """Schluessel X ist gerechnet; Beleg mit X\\n darf nicht als neuer Auftrag gelten."""
    urteil = _urteil(
        schluessel,
        rechnungsauftrag(auftragsschluessel=SCHLUESSEL_IM_BELEG + "\n"),
        lage=_Lage(dokumente={SCHLUESSEL_IM_BELEG: "RE-2026-08-001"}),
        nutzlast_art="rechnungsauftrag",
    )

    assert not urteil.angenommen
    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.auftragsschluessel"),
    ]


@pytest.mark.parametrize("wert", ["20261001", "2026-10-01\n", "2026-02-30"])
def test_datum_ohne_bindestriche_oder_mit_zeilenende_oder_unmoeglich(schluessel, wert):
    """JJJJ-MM-TT erst als Form, dann Kalender; Compact und Zeilenende fallen."""
    nutzlast = aufstellungsauftrag()
    nutzlast["zahlung"]["datum"] = wert

    urteil = _urteil(schluessel, nutzlast, nutzlast_art="aufstellungsauftrag")

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.zahlung.datum"),
    ]


def test_datum_jjjj_mm_tt_wird_angenommen(schluessel):
    nutzlast = aufstellungsauftrag()
    nutzlast["zahlung"]["datum"] = "2026-10-01"

    urteil = _urteil(schluessel, nutzlast, nutzlast_art="aufstellungsauftrag")

    assert urteil.angenommen, _befunde(urteil)


def test_fremdes_signaturverfahren_wird_abgelehnt(schluessel):
    """Nur das Verfahrensfeld weicht ab; Signaturbytes bleiben gueltig."""
    roh = beleg(schluessel[0], auftrag())
    inhalt = json.loads(roh)
    assert inhalt["signatur"]["verfahren"] == VERFAHREN
    inhalt["signatur"]["verfahren"] = "RSA"

    urteil = beleg_beurteilen(
        kanonisch(inhalt), _Lage(), schluessel_wurzel=schluessel[1],
    )

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", "$.signatur.verfahren")]


def test_beiblatt_ohne_gueltig_bis_macht_den_schluessel_unbrauchbar(schluessel):
    """gueltig_bis ist Pflicht; null bleibt erlaubt und heisst ohne Ablauf."""
    signieren, wurzel = schluessel
    ohne = {name: wert for name, wert in beiblatt().items() if name != "gueltig_bis"}
    beiblatt_ablegen(wurzel, ohne)

    urteil = beleg_beurteilen(
        beleg(signieren), _Lage(), schluessel_wurzel=wurzel,
    )

    assert not urteil.angenommen
    assert _befunde(urteil) == [("SCHLUESSEL_UNBEKANNT", "$.signatur.schluessel_id")]
    with pytest.raises(SchluesselUnbekannt, match="gueltig_bis"):
        schluessel_laden(ABSENDER_TANTIEMEN, SCHLUESSEL_ID, ERZEUGT_AM, wurzel=wurzel)


@pytest.mark.parametrize("pfad,aenderung", [
    ("$.absender", {"absender": "tantiemen-app\n"}),
    ("$.absender", {"absender": "Tantiemen-app"}),
    ("$.absender", {"absender": 4711}),
    ("$.empfaenger", {"empfaenger": "abgehakt\n"}),
    ("$.empfaenger", {"empfaenger": "Abgehakt"}),
    ("$.empfaenger", {"empfaenger": 42}),
    ("$.signatur.schluessel_id", {"schluessel_id": "tantiemen-2026-09\n"}),
    ("$.signatur.schluessel_id", {"schluessel_id": "Tantiemen-2026-09"}),
    ("$.signatur.schluessel_id", {"schluessel_id": 2026}),
])
def test_umschlag_kennung_muss_ganz_passen(schluessel, pfad, aenderung):
    """absender, empfaenger und signatur.schluessel_id: Form vor jedem Schluesselpfad.

    absender und empfaenger stehen in den signierten Bytes - der Umschlag
    wird deshalb mit dem unbrauchbaren Wert gebaut und neu signiert.
    schluessel_id liegt nur in der Signatur und wird nach dem Signieren gesetzt.
    """
    if pfad == "$.signatur.schluessel_id":
        inhalt = json.loads(beleg(schluessel[0], auftrag()))
        inhalt["signatur"]["schluessel_id"] = aenderung["schluessel_id"]
        roh = kanonisch(inhalt)
    else:
        roh = beleg(schluessel[0], auftrag(), **aenderung)

    urteil = beleg_beurteilen(roh, _Lage(), schluessel_wurzel=schluessel[1])

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", pfad)]
