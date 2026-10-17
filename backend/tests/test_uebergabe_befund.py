"""Der Befund je Uebergabebeleg (abgehakt#22): ein Pruefschritt, ein Ergebnis.

Das Lesen hat keine Wirkung. Der Befund entsteht an EINER Stelle und ist spaeter
der Inhalt der Quittung (§ 10) - deshalb steht er in einem Ergebnisobjekt und
nicht in der Tabellendarstellung. Ob die Quittung beim Lesen oder beim Knopfdruck
geschrieben wird, entscheidet Stufe 7; beides bleibt moeglich, solange der Befund
nicht in der Ansicht steckt.
"""

import base64
import copy
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services.uebergabe_befund import (
    Empfangslage,
    beleg_beurteilen,
)
from app.services.uebergabebeleg import (
    ABSENDER_TANTIEMEN,
    EMPFAENGER_ABGEHAKT,
    kanonisch,
    umschlag,
)

PARTNER_A = "3f5b1c80-0000-4000-8000-00000000000a"
PARTNER_B = "3f5b1c80-0000-4000-8000-00000000000b"
SCHLUESSEL_ID = "tantiemen-2026-09"
PROBE_SCHLUESSEL_ID = "tantiemen-probe-2026-09"
ERZEUGT = "2026-09-03T11:00:00Z"


@dataclass
class Probelage(Empfangslage):
    """Was der Empfaenger schon gesehen hat - im Test von Hand gesetzt."""

    zuletzt: Optional[tuple] = None
    kennungen: Optional[dict] = None
    partner: tuple = (PARTNER_A, PARTNER_B)

    def zuletzt_angenommen(self, absender: str):
        return self.zuletzt

    def sha_zu_beleg_id(self, beleg_id: str):
        return (self.kennungen or {}).get(beleg_id)

    def partner_bekannt(self, partner_id: str) -> bool:
        return partner_id in self.partner


@pytest.fixture
def schluessel(tmp_path):
    privat = Ed25519PrivateKey.generate()
    ordner = tmp_path / "schluessel" / ABSENDER_TANTIEMEN
    ordner.mkdir(parents=True)
    for kennung in (SCHLUESSEL_ID, PROBE_SCHLUESSEL_ID):
        (ordner / f"{kennung}.pub").write_bytes(
            privat.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
        )
        (ordner / f"{kennung}.json").write_text(
            # Ohne "probe": Ein Probeschluessel ist am Namen erkennbar, nicht
            # an einer Angabe im Beiblatt (§ 6, geschlossener Feldbestand).
            json.dumps({
                "schluessel_id": kennung,
                "absender": ABSENDER_TANTIEMEN,
                "verfahren": "Ed25519",
                "gueltig_von": "2026-09-01T00:00:00Z",
                "gueltig_bis": None,
            }),
            encoding="utf-8",
        )
    return privat.sign, tmp_path / "schluessel"


def _auftrag(**aenderungen) -> dict:
    nutzlast = {
        "abrechnungsquartal": "2026-Q2",
        "projekt": {"id": "probe", "name": "Probeverlag"},
        "bemessung": {
            "erloes_netto": "797.30",
            "direktkosten_netto": "100.00",
            "deckungsbeitrag_netto": "697.30",
        },
        "grundlagen": [{
            "belegnummer": "90145",
            "beleg_sha256": "9edc0b19fcde7cc2d1aa0d46cd8412dc405660176e0065a28e983a0179dc61da",
            "leistungsperiode": "2026-04",
            "erloes_netto": "28.00",
        }],
        "gutschriften": [{
            "beteiligter": {"partner_id": PARTNER_A, "anzeigename": "Autorin A"},
            "typcode": "389",
            "leistungszeitraum": {"von": "2026-04-01", "bis": "2026-06-30"},
            "positionen": [{
                "nr": 1,
                "bezeichnung": "Beteiligung am Deckungsbeitrag 2026-Q2",
                "herleitung": {"basis_netto": "697.30", "satz": "25.00"},
                "netto": "174.33",
            }],
            "summe": {"netto": "174.33"},
        }],
        "vortraege": [],
    }
    nutzlast.update(aenderungen)
    return nutzlast


def _beleg(schluessel, nutzlast, **umschlag_aenderungen) -> bytes:
    signieren, _ = schluessel
    felder = dict(
        nutzlast=nutzlast,
        nutzlast_art="abrechnungsauftrag",
        beleg_id="11111111-2222-4333-8444-555555555555",
        erzeugt_am=ERZEUGT,
        absender=ABSENDER_TANTIEMEN,
        empfaenger=EMPFAENGER_ABGEHAKT,
        vorgaenger_hash=None,
        schluessel_id=SCHLUESSEL_ID,
        signierer=signieren,
    )
    felder.update(umschlag_aenderungen)
    return umschlag(**felder)


def _urteil(schluessel, roh, lage=None):
    return beleg_beurteilen(roh, lage or Probelage(), schluessel_wurzel=schluessel[1])


def _codes(urteil) -> list:
    return [f.code for f in urteil.feststellungen]


def test_ein_gueltiger_auftrag_wird_angenommen(schluessel):
    urteil = _urteil(schluessel, _beleg(schluessel, _auftrag()))

    assert urteil.angenommen, _codes(urteil)
    assert urteil.feststellungen == ()
    assert urteil.beleg_id == "11111111-2222-4333-8444-555555555555"
    assert urteil.abrechnungsquartal == "2026-Q2"
    assert urteil.projekt == "Probeverlag"
    assert urteil.zahl_gutschriften == 1
    assert str(urteil.summe_netto) == "174.33"


def test_der_befund_nennt_immer_die_bytes_die_er_beurteilt(schluessel):
    roh = _beleg(schluessel, _auftrag())
    urteil = _urteil(schluessel, roh)

    assert urteil.beleg_sha256 == hashlib.sha256(roh).hexdigest()


def test_ein_unlesbarer_beleg_nennt_den_hash_und_keine_kennung(schluessel):
    urteil = _urteil(schluessel, b'{"format_version": "1.5", "beleg')

    assert not urteil.angenommen
    assert _codes(urteil) == ["BELEG_UNLESBAR"]
    assert urteil.feststellungen[0].pfad == "$"
    assert urteil.beleg_id is None
    assert len(urteil.beleg_sha256) == 64


@pytest.mark.parametrize("feld", ["steuer", "brutto", "steuersatz"])
def test_steuerfelder_an_der_position_sind_unbekannte_felder(schluessel, feld):
    """Der Auftrag traegt nur netto. Nicht weil der Wert falsch waere, sondern
    weil sonst zwei Stellen dieselbe Zahl behaupten."""
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["positionen"][0][feld] = "7.00"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert not urteil.angenommen
    assert _codes(urteil) == ["UNBEKANNTES_FELD"]
    assert urteil.feststellungen[0].pfad.endswith(feld)


def test_steuerkategorie_an_der_gutschrift_ist_ein_unbekanntes_feld(schluessel):
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["steuerkategorie"] = "S"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["UNBEKANNTES_FELD"]
    assert urteil.feststellungen[0].pfad.endswith("steuerkategorie")


def test_ein_fehlendes_pflichtfeld_ist_kein_unbekanntes_feld(schluessel):
    """Das Feld ist bekannt, es ist nur nicht da."""
    nutzlast = _auftrag()
    del nutzlast["gutschriften"][0]["summe"]

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["PFLICHTFELD_FEHLT"]
    assert urteil.feststellungen[0].pfad.endswith("summe")


def test_die_summe_muss_ohne_toleranz_aufgehen(schluessel):
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["summe"]["netto"] = "174.34"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["SUMME_STIMMT_NICHT"]
    assert urteil.feststellungen[0].erwartet == "174.33"
    assert urteil.feststellungen[0].erhalten == "174.34"


def test_die_herleitung_wird_nachgerechnet(schluessel):
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["positionen"][0]["herleitung"]["satz"] = "20.00"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["SUMME_STIMMT_NICHT"]


def test_kaufmaennisch_gerundet_nicht_bankers_rounding(schluessel):
    """697.30 x 25 % ist 174.325; der Auftrag nennt 174.33.

    Pythons Standard ROUND_HALF_EVEN ergaebe 174.32 und wuerde den gueltigen
    Vektor ablehnen."""
    urteil = _urteil(schluessel, _beleg(schluessel, _auftrag()))

    assert urteil.angenommen, _codes(urteil)


def test_ein_satz_mit_sechs_nachkommastellen_wird_nicht_vorher_gerundet(schluessel):
    """797.30 x 33.333333 % sind 265.77. Mit auf zwei Stellen gerundetem Satz
    waeren es 265.74, und der gueltige Vektor flaege raus."""
    nutzlast = _auftrag()
    gutschrift = nutzlast["gutschriften"][0]
    gutschrift["positionen"][0]["herleitung"] = {"basis_netto": "797.30", "satz": "33.333333"}
    gutschrift["positionen"][0]["netto"] = "265.77"
    gutschrift["summe"]["netto"] = "265.77"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert urteil.angenommen, _codes(urteil)


def test_eine_position_ohne_herleitung_wird_ungeprueft_uebernommen(schluessel):
    """Ihr Schluessel ist Innenverhaeltnis und geht abgehakt nichts an."""
    nutzlast = _auftrag()
    del nutzlast["gutschriften"][0]["positionen"][0]["herleitung"]

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert urteil.angenommen, _codes(urteil)


def test_grundlagen_duerfen_kleiner_sein_als_der_erloes(schluessel):
    """`grundlagen` ist ein Auszug. Ein Pruefhaken auf Gleichheit wuerde jeden
    echten Auftrag ablehnen: als signierte Erloesmeldung kommt heute nur ein Kanal."""
    urteil = _urteil(schluessel, _beleg(schluessel, _auftrag()))

    assert urteil.angenommen, _codes(urteil)


def test_grundlagen_groesser_als_der_erloes_geht_nicht(schluessel):
    nutzlast = _auftrag()
    nutzlast["grundlagen"][0]["erloes_netto"] = "800.00"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["SUMME_STIMMT_NICHT"]


def test_unbekannte_partner_id_wird_gemeldet(schluessel):
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["beteiligter"]["partner_id"] = "00000000-dead-4000-8000-000000000000"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert not urteil.angenommen
    assert _codes(urteil) == ["PARTNER_ID_UNBEKANNT"]


def test_ein_beleg_an_jemand_anderen_wird_abgelehnt(schluessel):
    roh = _beleg(schluessel, _auftrag(), empfaenger="tantiemen-app")

    urteil = _urteil(schluessel, roh)

    assert _codes(urteil) == ["EMPFAENGER_FREMD"]


def test_eine_erloesmeldung_liest_dieser_empfaenger_nicht(schluessel):
    roh = _beleg(schluessel, _auftrag(), nutzlast_art="erloesmeldung")

    urteil = _urteil(schluessel, roh)

    assert _codes(urteil) == ["NUTZLASTART_UNBEKANNT"]


def test_eine_art_die_das_protokoll_nicht_fuehrt(schluessel):
    roh = _beleg(schluessel, _auftrag(), nutzlast_art="kontoauszug")

    urteil = _urteil(schluessel, roh)

    assert _codes(urteil) == ["NUTZLASTART_UNBEKANNT"]


def test_ein_zusaetzliches_feld_am_umschlag(schluessel):
    roh = _beleg(schluessel, _auftrag())
    beleg = json.loads(roh)
    beleg["bonusfeld"] = "kommt nicht vor"
    urteil = _urteil(schluessel, kanonisch(beleg))

    assert _codes(urteil) == ["UNBEKANNTES_FELD"]
    assert urteil.feststellungen[0].pfad == "$.bonusfeld"


def test_eine_verdrehte_signatur(schluessel):
    beleg = json.loads(_beleg(schluessel, _auftrag()))
    roh_signatur = bytearray(base64.b64decode(beleg["signatur"]["wert"]))
    roh_signatur[0] ^= 0x01
    beleg["signatur"]["wert"] = base64.b64encode(bytes(roh_signatur)).decode("ascii")

    urteil = _urteil(schluessel, kanonisch(beleg))

    assert _codes(urteil) == ["SIGNATUR_UNGUELTIG"]


def test_eine_nutzlast_die_nicht_zu_ihrem_hash_passt(schluessel):
    beleg = json.loads(_beleg(schluessel, _auftrag()))
    beleg["nutzlast"]["abrechnungsquartal"] = "2026-Q3"

    urteil = _urteil(schluessel, kanonisch(beleg))

    assert _codes(urteil) == ["NUTZLAST_HASH_FALSCH"]


def test_ein_schluessel_den_hier_niemand_abgelegt_hat(schluessel):
    roh = _beleg(schluessel, _auftrag())
    beleg = json.loads(roh)
    beleg["signatur"]["schluessel_id"] = "erfunden-2026-09"

    urteil = _urteil(schluessel, kanonisch(beleg))

    assert _codes(urteil) == ["SCHLUESSEL_UNBEKANNT"]


def test_derselbe_beleg_ein_zweites_mal_ist_keine_ablehnung(schluessel):
    """§ 11: zweimal eingelesen heisst einmal gewirkt - aber nicht abgelehnt."""
    roh = _beleg(schluessel, _auftrag())
    lage = Probelage(kennungen={"11111111-2222-4333-8444-555555555555":
                                hashlib.sha256(roh).hexdigest()})

    urteil = _urteil(schluessel, roh, lage)

    assert urteil.angenommen
    assert urteil.bereits_verarbeitet
    assert urteil.feststellungen == ()


def test_dieselbe_kennung_mit_anderem_inhalt_ist_ein_widerspruch(schluessel):
    roh = _beleg(schluessel, _auftrag())
    lage = Probelage(kennungen={"11111111-2222-4333-8444-555555555555": "a" * 64})

    urteil = _urteil(schluessel, roh, lage)

    assert not urteil.angenommen
    assert _codes(urteil) == ["BELEG_ID_WIDERSPRUCH"]


def test_die_kette_darf_nicht_springen(schluessel):
    roh = _beleg(schluessel, _auftrag(), vorgaenger_hash="f" * 64)
    lage = Probelage(zuletzt=("a" * 64, datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)))

    urteil = _urteil(schluessel, roh, lage)

    assert _codes(urteil) == ["KETTE_SPRINGT"]


def test_die_kette_darf_nicht_neu_beginnen(schluessel):
    roh = _beleg(schluessel, _auftrag(), vorgaenger_hash=None)
    lage = Probelage(zuletzt=("a" * 64, datetime(2026, 9, 3, 10, 0, tzinfo=timezone.utc)))

    urteil = _urteil(schluessel, roh, lage)

    assert _codes(urteil) == ["KETTE_BEGINNT_NEU"]


def test_die_zeit_darf_nicht_rueckwaerts_laufen(schluessel):
    roh = _beleg(schluessel, _auftrag(), vorgaenger_hash="a" * 64)
    lage = Probelage(zuletzt=("a" * 64, datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)))

    urteil = _urteil(schluessel, roh, lage)

    assert _codes(urteil) == ["ERZEUGT_AM_RUECKWAERTS"]


def test_gleiche_zeit_ist_erlaubt(schluessel):
    """Ein Sammellauf traegt denselben Zeitstempel."""
    roh = _beleg(schluessel, _auftrag(), vorgaenger_hash="a" * 64)
    lage = Probelage(zuletzt=("a" * 64, datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)))

    urteil = _urteil(schluessel, roh, lage)

    assert urteil.angenommen, _codes(urteil)


def test_ein_auftrag_ohne_gutschriften_wirkt_nicht(schluessel):
    urteil = _urteil(schluessel, _beleg(schluessel, _auftrag(gutschriften=[])))

    assert not urteil.angenommen
    assert _codes(urteil) == ["PFLICHTFELD_FEHLT"]


def test_ein_typcode_ausserhalb_des_wertevorrats(schluessel):
    """Bekanntes Feld, unbrauchbarer Wert: 381 und 389 sind zwei verschiedene
    Belege, alles andere ist keiner. Der Befund faellt im LESER, nicht erst
    beim Knopfdruck."""
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["typcode"] = "999"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad.endswith("typcode")
    assert urteil.feststellungen[0].erhalten == "999"


def test_ein_erzeugt_am_das_kein_zeitpunkt_ist(schluessel):
    roh = _beleg(schluessel, _auftrag(), erzeugt_am="neulich")

    urteil = _urteil(schluessel, roh)

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.erzeugt_am"


def test_ein_betrag_der_keine_zahl_ist(schluessel):
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["positionen"][0]["netto"] = "hundert"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad.endswith("netto")


def test_ein_probeschluessel_gilt_im_echtlauf_nicht(schluessel, monkeypatch):
    """Ein Probeschluessel ist am Namen erkennbar (`-probe-`). Der Empfaenger
    darf ihn im Echtlauf nicht annehmen - erkannt an der schluessel_id, nicht an
    einer Umgebungsvariablen des Absenders."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "installation_mode", "production")
    roh = _beleg(schluessel, _auftrag(), schluessel_id=PROBE_SCHLUESSEL_ID)

    urteil = _urteil(schluessel, roh)

    assert _codes(urteil) == ["SCHLUESSEL_UNBEKANNT"]


def test_ein_probeschluessel_gilt_in_der_testinstanz(schluessel, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "installation_mode", "testinstanz")
    roh = _beleg(schluessel, _auftrag(), schluessel_id=PROBE_SCHLUESSEL_ID)

    urteil = _urteil(schluessel, roh)

    assert urteil.angenommen, _codes(urteil)


def test_eine_gleitkommazahl_in_der_nutzlast_ist_ein_befund(schluessel):
    """RFC 8785 ohne Gleitkommazahlen: kanonisch() wirft UebergabeFehler, und
    vorher war das eine Ausnahme, die die ganze Belegliste lahmlegte (500).

    WERT_UNBRAUCHBAR, nicht BELEG_UNLESBAR: Die Datei ist lesbar, das Feld ist
    bekannt, nur der Wert kanonisiert nicht (protokoll.py zu WERT_UNBRAUCHBAR).
    Die Bytes werden direkt geschrieben: signieren laesst sich eine Nutzlast
    mit Gleitkommazahl ohnehin nicht, der Befund entsteht vor der Signatur."""
    beleg = json.loads(_beleg(schluessel, _auftrag()))
    beleg["nutzlast"]["bemessung"]["erloes_netto"] = 797.30
    roh = json.dumps(beleg).encode("utf-8")

    urteil = _urteil(schluessel, roh)

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.bemessung.erloes_netto"


@pytest.mark.parametrize("angabe", ["2026-09-03T11:00:00", "2026-09-03"])
def test_ein_erzeugt_am_ohne_zone_ist_ein_befund(schluessel, angabe):
    """Ohne Zeitzone parst fromisoformat eine naive datetime, und erst der
    Vergleich mit dem zeitzonenbewussten Beiblatt des Schluessels warf einen
    TypeError - vor jeder Signaturpruefung, also genuegte jede Datei. RFC 3339
    verlangt die Zone; ohne sie ist der Wert unbrauchbar, nicht der Beleg."""
    roh = _beleg(schluessel, _auftrag(), erzeugt_am=angabe)

    urteil = _urteil(schluessel, roh)

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.erzeugt_am"


def test_nan_als_positionsbetrag_ist_ein_befund(schluessel):
    """Decimal parst "NaN" anstandslos: Der Gleichheitsvergleich mit NaN ist
    still False, der Ordnungsvergleich (erloes, Grundlagen) wirft. So wurde
    aus "NaN" ein SUMME_STIMMT_NICHT oder ein Crash - nie aber der Befund,
    der dorthin gehoert. Ein Wert, der mit nichts vergleichbar ist, ist
    keine Zahl. Seit #163 prueft der Leser die Form am Feld selbst: Beide
    NaN-Angaben sind je ein Befund, nicht mehr nur die zuerst gelesene."""
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["positionen"][0]["netto"] = "NaN"
    nutzlast["gutschriften"][0]["summe"]["netto"] = "NaN"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR", "WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.gutschriften[0].positionen[0].netto"


def test_nan_als_erloes_ist_ein_befund(schluessel):
    """NaN im Erloes wirft heute decimal.InvalidOperation im Vergleich mit
    den Grundlagen - eine Ausnahme, kein Befund. Ein Wert, der mit nichts
    vergleichbar ist, ist keine Zahl."""
    nutzlast = _auftrag()
    nutzlast["bemessung"]["erloes_netto"] = "NaN"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.bemessung.erloes_netto"


def test_ein_objekt_statt_der_gutschriften_liste_ist_ein_befund(schluessel):
    """Vorher stillschweigend angenommen; erst die Wirkung lief in einen
    TypeError (string indices). Die Formprobe gehoert in den Leser, vor die
    Annahme - das Feld ist bekannt und da, nur seine Form ist unbrauchbar."""
    nutzlast = _auftrag()
    nutzlast["gutschriften"] = nutzlast["gutschriften"][0]

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.gutschriften"


def test_eine_zeichenkette_statt_der_positionen_liste_ist_ein_befund(schluessel):
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["positionen"] = "eine Position als Text"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.gutschriften[0].positionen"


def test_ein_leistungszeitraum_der_kein_datum_ist_ein_befund(schluessel):
    """Vorher angenommen; erst das Anlegen der Rechnung warf beim Lesen des
    Zeitraums einen ValueError. Die Wertprobe gehoert vor die Annahme, und
    sie verlangt dasselbe Datum, das die Wirkung spaeter liest."""
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["leistungszeitraum"]["von"] = "irgendwann"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == (
        "$.nutzlast.gutschriften[0].leistungszeitraum.von"
    )


def test_ein_leistungszeitraum_der_rueckwaerts_laeuft_ist_ein_befund(schluessel):
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["leistungszeitraum"]["von"] = "2026-06-30"
    nutzlast["gutschriften"][0]["leistungszeitraum"]["bis"] = "2026-04-01"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.gutschriften[0].leistungszeitraum"


# ── § 2 und § 4: die Formen des Formats (#163). Eine Abweichung ist kein
# Rechenproblem, sondern ein unbrauchbarer WERT an einem bekannten Feld; der
# Befund nennt den Pfad, damit der Absender die Stelle reparieren kann.

@pytest.mark.parametrize("form", [
    "174.335",    # drei Nachkommastellen statt genau zwei
    "1.7433E2",   # Exponentialschreibweise
    " 174.33",    # fuehrendes Leerzeichen
    "174.3300",   # wertgleich, aber falsch geschrieben
    "Infinity",   # keine endliche Zahl
    "NaN",        # mit nichts vergleichbar
    174,          # JSON-Zahl statt Zeichenkette
])
def test_ein_betrag_der_nicht_der_geldform_entspricht_ist_ein_befund(schluessel, form):
    """§ 4: Geld ist eine JSON-Zeichenkette mit Dezimalpunkt und GENAU zwei
    Nachkommastellen. Decimal hat alle diese Formen still geschluckt - " 174.33"
    und "174.3300" sogar als wertgleich - und die Wirkung rundete dann heimlich.
    Deshalb prueft der Leser die Form, bevor irgendwer rechnet."""
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["positionen"][0]["netto"] = form

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert not urteil.angenommen
    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == (
        "$.nutzlast.gutschriften[0].positionen[0].netto"
    )


def test_auch_die_bemessung_traegt_die_geldform(schluessel):
    """direktkosten_netto wurde vor #163 auf keinen Wert geprueft. Die
    Formprobe gilt fuer ALLE Geldfelder des Verzeichnisses, nicht nur fuer
    die, die vorher in eine Rechnung flossen."""
    nutzlast = _auftrag()
    nutzlast["bemessung"]["direktkosten_netto"] = "100.0"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert not urteil.angenommen
    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.bemessung.direktkosten_netto"


def test_ein_satz_mit_einer_nachkommastelle_ist_ein_befund(schluessel):
    """§ 4, Klarstellung 2026-10-17: Der Satz ist vom Geld getrennt und traegt
    MINDESTENS zwei Nachkommastellen. "33.3" ist keine Satzform. Die Gegenprobe
    steht oben: "33.333333" bleibt gueltig
    (test_ein_satz_mit_sechs_nachkommastellen_wird_nicht_vorher_gerundet)."""
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["positionen"][0]["herleitung"]["satz"] = "33.3"

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert not urteil.angenommen
    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == (
        "$.nutzlast.gutschriften[0].positionen[0].herleitung.satz"
    )


@pytest.mark.parametrize("angabe", [
    "2026-09-03T11:00:00.123Z",   # Bruchteile einer Sekunde
    "2026-09-03T13:00:00+02:00",  # Offset statt UTC
])
def test_ein_erzeugt_am_in_anderer_schreibweise_ist_ein_befund(schluessel, angabe):
    """§ 2: UTC, sekundengenau, ohne Bruchteile - die Form
    YYYY-MM-DDTHH:MM:SSZ. Beide Schreibweisen nennen denselben Augenblick,
    und der Leser parste beide anstandslos; erlaubt ist nur die eine."""
    roh = _beleg(schluessel, _auftrag(), erzeugt_am=angabe)

    urteil = _urteil(schluessel, roh)

    assert not urteil.angenommen
    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.erzeugt_am"


# ── § 3: Die Datei IST die kanonische Form (#165). Die Signatur gilt ueber
# die gelesenen Bytes, nicht ueber ein neu kanonisiertes Objekt - wer die
# Pruefung ueber das Objekt macht, nimmt jede Schreibweise desselben Belegs an,
# und beleg_sha256 entsteht trotzdem ueber die abweichende Datei: Die Kette
# reisst beim naechsten Beleg, der diesen Hash als vorgaenger nennt.

def test_eine_eingerueckte_ansicht_desselben_belegs_wird_abgelehnt(schluessel):
    """§ 3, Gegenstueck zur Annahme oben: derselbe Beleg, mit Einrueckung neu
    geschrieben, ist eine ANDERE Datei. Vor #165 pruefte der Leser die
    Signatur ueber das neu kanonisierte Objekt und nahm sie an."""
    roh = _beleg(schluessel, _auftrag())
    eingerueckt = json.dumps(json.loads(roh), indent=2).encode("utf-8")

    urteil = _urteil(schluessel, eingerueckt)

    assert not urteil.angenommen
    assert _codes(urteil) == ["SIGNATUR_UNGUELTIG"]
    assert urteil.beleg_sha256 == hashlib.sha256(eingerueckt).hexdigest()


def test_eine_datei_mit_doppeltem_namen_wird_abgelehnt(schluessel):
    """json.loads laesst bei einem doppelten Namen still den letzten gewinnen.
    Die Datei ist damit nie die kanonische Form; der Befund entsteht schon beim
    Parsen, damit "der letzte gewinnt" gar nicht erst passiert."""
    roh = _beleg(schluessel, _auftrag())
    text = roh.decode("utf-8")
    doppelt = text.replace(
        '"empfaenger":"abgehakt"',
        '"empfaenger":"abgehakt","empfaenger":"abgehakt"',
        1,
    ).encode("utf-8")

    urteil = _urteil(schluessel, doppelt)

    assert not urteil.angenommen
    assert _codes(urteil) == ["SIGNATUR_UNGUELTIG"]


def test_der_unveraenderte_gueltige_beleg_wird_weiter_angenommen(schluessel):
    """Die Gegenprobe zu den beiden oben: der Beleg, wie ihn der Absender
    kanonisch geschrieben hat, bleibt angenommen - die Datei IST die Form."""
    roh = _beleg(schluessel, _auftrag())

    urteil = _urteil(schluessel, roh)

    assert urteil.angenommen, _codes(urteil)


def test_ein_typcode_als_zahl_ist_ein_befund(schluessel):
    """§ 4: typcode ist eine JSON-Zeichenkette ("389"), keine Zahl. str()
    machte aus der Zahl 389 still einen gueltigen Code, und der Absender
    erfaehrt nie, dass sein Beleg falsch gebaut ist."""
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["typcode"] = 389

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert not urteil.angenommen
    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.gutschriften[0].typcode"


# ── § 10: je Grund ein Befund (#169). Die Quittung nennt jeden Grund mit
# Pfad; der Leser prueft deshalb alle Wertproben, nicht bloss bis zur ersten.

def test_je_grund_ein_befund_ueber_alle_gutschriften(schluessel):
    """Ein typcode ausserhalb des Vorrats in Gutschrift 0 UND eine Summe, die
    nicht aufgeht, in Gutschrift 1: zwei Gruende, zwei Befunde, je mit eigenem
    Pfad. Der Leser meldete bisher nur den ersten - der Absender reparierte die
    eine Stelle, reichte wieder ein, und erst dann kam der zweite Befund."""
    nutzlast = _auftrag()
    nutzlast["gutschriften"][0]["typcode"] = "999"
    zweite = copy.deepcopy(nutzlast["gutschriften"][0])
    zweite["typcode"] = "389"
    zweite["summe"]["netto"] = "999.99"
    nutzlast["gutschriften"].append(zweite)

    urteil = _urteil(schluessel, _beleg(schluessel, nutzlast))

    assert not urteil.angenommen
    assert _codes(urteil) == ["WERT_UNBRAUCHBAR", "SUMME_STIMMT_NICHT"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.gutschriften[0].typcode"
    assert urteil.feststellungen[1].pfad == "$.nutzlast.gutschriften[1].summe.netto"
