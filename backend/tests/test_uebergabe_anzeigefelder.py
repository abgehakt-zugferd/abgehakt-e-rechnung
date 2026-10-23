"""Eine Quelle fuer Anzeigefelder: Belegurteil, Liste und Einlese-Skript (#207).

Oeffentliche Grenzen: beleg_beurteilen (Urteil), anzeigefelder (kaputte Nutzlast),
annahme_stand (Skript-Text).
"""

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
from app.services.uebergabe_listenzeile import anzeigefelder, annahme_stand
from tests.helpers.uebergabe import (
    PARTNER_A,
    aufstellungsauftrag,
    beleg,
    probe_anlagen,
    rechnungsauftrag,
    schluesselpaar,
)


@pytest.fixture
def schluessel(tmp_path):
    return schluesselpaar(tmp_path / "schluessel")


class _Lage(Empfangslage):
    def __init__(self, partner=(), anlagen=None):
        self._partner = partner
        self._anlagen = anlagen if anlagen is not None else {}

    def partner_bekannt(self, partner_id: str) -> bool:
        return partner_id in self._partner

    def anlagen_bytes(self, sha256: str):
        return self._anlagen.get(sha256)


def test_rechnungsauftrag_urteil_traegt_gegenstand_zeitraum_summe(schluessel):
    signieren, wurzel = schluessel
    roh = beleg(signieren, rechnungsauftrag(), nutzlast_art="rechnungsauftrag")

    urteil = beleg_beurteilen(
        roh, _Lage(partner=(PARTNER_A,)), schluessel_wurzel=wurzel,
    )

    assert urteil.angenommen
    assert urteil.gegenstand == "Plattform Beispiel GmbH"
    assert urteil.zeitraum == "2026-02"
    assert "171,34" in (urteil.summe or "")


def test_annahme_stand_zeigt_kunde_statt_null_gutschriften(schluessel):
    signieren, wurzel = schluessel
    roh = beleg(signieren, rechnungsauftrag(), nutzlast_art="rechnungsauftrag")
    urteil = beleg_beurteilen(
        roh, _Lage(partner=(PARTNER_A,)), schluessel_wurzel=wurzel,
    )

    stand = annahme_stand(urteil)

    assert "Plattform Beispiel GmbH" in stand
    assert "2026-02" in stand
    assert "171,34" in stand
    assert "Gutschrift" not in stand
    assert "0 netto" not in stand


def test_annahme_stand_aufstellungsauftrag_mit_waehrung(schluessel):
    signieren, wurzel = schluessel
    roh = beleg(
        signieren, aufstellungsauftrag(), nutzlast_art="aufstellungsauftrag",
    )
    urteil = beleg_beurteilen(
        roh,
        _Lage(partner=(PARTNER_A,), anlagen=probe_anlagen()),
        schluessel_wurzel=wurzel,
    )

    stand = annahme_stand(urteil)

    assert urteil.angenommen, [f.code for f in urteil.feststellungen]
    assert "Beispiel Services LLC" in stand
    assert "4,84" in stand
    assert "USD" in stand
    assert "Gutschrift" not in stand


@pytest.mark.parametrize("art,nutzlast", [
    ("abrechnungsauftrag", {
        "abrechnungsquartal": "2026-Q2",
        "projekt": "kein-objekt",
        "gutschriften": "keine-liste",
    }),
    ("rechnungsauftrag", {
        "kunde": "nur-text",
        "leistungszeitraum": {"von": "2026-02-01", "bis": "2026-02-28"},
    }),
    ("aufstellungsauftrag", {
        "kunde": {"anzeigename": "Beispiel Services LLC"},
        "leistungszeitraum": "kein-objekt",
        "betraege": "fehlt",
    }),
])
def test_anzeigefelder_ertragen_kaputte_nutzlast(art, nutzlast):
    felder = anzeigefelder(nutzlast, art)

    assert set(felder) == {"gegenstand", "zeitraum", "summe"}
    assert all(isinstance(felder[k], str) for k in felder)
