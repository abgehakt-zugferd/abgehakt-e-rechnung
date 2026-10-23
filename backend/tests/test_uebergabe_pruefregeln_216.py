"""Pruefregeln ohne Testbiss (#216): Kettenanfang, Geldgrenzen, doppelter Name.

Jeder Fall geht ueber beleg_beurteilen. Testdaten nur erfunden
(helpers/uebergabe). Probelage ohne Stand, wo der Kettenanfang geprueft wird.
"""

from dataclasses import dataclass
from typing import Optional

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
from tests.helpers.uebergabe import (
    PARTNER_A,
    aufstellungsauftrag,
    auftrag,
    beleg,
    probe_anlagen,
    schluesselpaar,
)


@dataclass
class Probelage(Empfangslage):
    zuletzt: Optional[tuple] = None
    partner: tuple = (PARTNER_A,)

    def zuletzt_angenommen(self, absender: str):
        return self.zuletzt

    def partner_bekannt(self, partner_id: str) -> bool:
        return partner_id in self.partner

    def anlagen_bytes(self, sha256: str):
        return probe_anlagen().get(sha256)


@pytest.fixture
def schluessel(tmp_path):
    return schluesselpaar(tmp_path)


def _urteil_abrechnung(schluessel, nutzlast, lage=None, **umschlag):
    roh = beleg(schluessel[0], nutzlast, **umschlag)
    return beleg_beurteilen(
        roh, lage or Probelage(), schluessel_wurzel=schluessel[1],
    )


def _urteil_aufstellung(schluessel, nutzlast, lage=None):
    roh = beleg(
        schluessel[0], nutzlast, nutzlast_art="aufstellungsauftrag",
    )
    if lage is None:
        lage = Probelage()
    return beleg_beurteilen(roh, lage, schluessel_wurzel=schluessel[1])


def _codes(urteil) -> list:
    return [f.code for f in urteil.feststellungen]


# ---- B12: Kettenanfang bei leerem Stand ----


def test_leerer_stand_mit_vorgaenger_ist_kette_springt(schluessel):
    """Ohne gemerkten Eingang darf der Beleg keinen vorgaenger_hash nennen."""
    roh = beleg(schluessel[0], auftrag(), vorgaenger_hash="f" * 64)
    urteil = beleg_beurteilen(
        roh, Probelage(zuletzt=None), schluessel_wurzel=schluessel[1],
    )

    assert not urteil.angenommen
    assert _codes(urteil) == ["KETTE_SPRINGT"]
    assert urteil.feststellungen[0].pfad == "$.vorgaenger_hash"


# ---- B14a: Summe grundlagen gegen erloes_netto ----


def test_grundlagen_gleich_dem_erloes_sind_erlaubt(schluessel):
    """§ 8: Σ grundlagen ≤ bemessung.erloes_netto (test_vektoren.sh:388;
    erwartung.json: „Anders als § 8 (dort ≤)“). Gleichheit ist angenommen."""
    nutzlast = auftrag()
    nutzlast["grundlagen"][0]["erloes_netto"] = nutzlast["bemessung"]["erloes_netto"]

    urteil = _urteil_abrechnung(schluessel, nutzlast)

    assert urteil.angenommen, _codes(urteil)


# ---- B14b: Quellensteuer Form und Grenze ----


def test_quellensteuer_null_ist_gueltig(schluessel):
    """protokoll.json aufstellungsauftrag.summen: quellensteuer >= 0.00."""
    nutzlast = aufstellungsauftrag(betraege={
        "brutto": "6.92", "quellensteuer": "0.00", "netto": "6.92",
    })

    urteil = _urteil_aufstellung(schluessel, nutzlast)

    assert urteil.angenommen, _codes(urteil)


def test_quellensteuer_ohne_zwei_nachkommastellen_ist_unbrauchbar(schluessel):
    """GELDFORM verlangt genau zwei Nachkommastellen; „5.5“ ist keine."""
    nutzlast = aufstellungsauftrag(betraege={
        "brutto": "7.50", "quellensteuer": "5.5", "netto": "2.00",
    })

    urteil = _urteil_aufstellung(schluessel, nutzlast)

    assert not urteil.angenommen
    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.betraege.quellensteuer"


def test_quellensteuer_knapp_unter_null_wird_abgelehnt(schluessel):
    """Gegenprobe zu < -1: -0.01 ist negativ und muss SUMME_STIMMT_NICHT
    tragen. Der Fall mit -1.00 steht schon in test_aufstellungsauftrag_leser."""
    nutzlast = aufstellungsauftrag(betraege={
        "brutto": "5.84", "quellensteuer": "-0.01", "netto": "5.85",
    })

    urteil = _urteil_aufstellung(schluessel, nutzlast)

    assert _codes(urteil) == ["SUMME_STIMMT_NICHT"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.betraege.quellensteuer"


# ---- B14c: typcode ausserhalb TYPCODE_BELEGART ----


def test_gutschrift_typcode_380_ist_unbrauchbar(schluessel):
    """380 ist BT-3-Rechnung, nicht im Auftragsvorrat {381, 389}. Der Leser
    prueft gegen TYPCODE_BELEGART (uebergabe_befund:839), nicht gegen eine
    zweite Liste."""
    nutzlast = auftrag()
    nutzlast["gutschriften"][0]["typcode"] = "380"

    urteil = _urteil_abrechnung(schluessel, nutzlast)

    assert not urteil.angenommen
    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.nutzlast.gutschriften[0].typcode"


# ---- B24: doppelter Name, Parse-Schicht ----


def test_doppelter_name_nennt_den_feldnamen_im_erhalten(schluessel):
    """Die Parse-Schicht (_objekt_aus_paaren) setzt erhalten=Name. Die
    Kanonprobe darunter liefert denselben Code ohne erhalten. Dieser Test
    sichert die Schicht: faellt die Parse-Pruefung aus, bleibt die Ablehnung
    durch die Kanonprobe, aber ohne Feldnamen."""
    roh = beleg(schluessel[0], auftrag())
    doppelt = roh.decode("utf-8").replace(
        '"empfaenger":"abgehakt"',
        '"empfaenger":"abgehakt","empfaenger":"abgehakt"',
        1,
    ).encode("utf-8")

    urteil = beleg_beurteilen(
        doppelt, Probelage(), schluessel_wurzel=schluessel[1],
    )

    assert not urteil.angenommen
    assert _codes(urteil) == ["SIGNATUR_UNGUELTIG"]
    assert urteil.feststellungen[0].pfad == "$"
    assert urteil.feststellungen[0].erhalten == "empfaenger"
