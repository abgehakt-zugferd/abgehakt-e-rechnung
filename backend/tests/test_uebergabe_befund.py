"""Der Befund je Uebergabebeleg (abgehakt#22): ein Pruefschritt, ein Ergebnis.

Das Lesen hat keine Wirkung. Der Befund entsteht an EINER Stelle und ist spaeter
der Inhalt der Quittung (§ 10) - deshalb steht er in einem Ergebnisobjekt und
nicht in der Tabellendarstellung. Ob die Quittung beim Lesen oder beim Knopfdruck
geschrieben wird, entscheidet Stufe 7; beides bleibt moeglich, solange der Befund
nicht in der Ansicht steckt.
"""

import base64
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
            json.dumps({
                "schluessel_id": kennung,
                "absender": ABSENDER_TANTIEMEN,
                "verfahren": "Ed25519",
                "gueltig_von": "2026-09-01T00:00:00Z",
                "gueltig_bis": None,
                "probe": kennung == PROBE_SCHLUESSEL_ID,
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
    waeren es 265.73, und der gueltige Vektor flaege raus."""
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
