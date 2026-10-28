"""#230 Teil B: gutschriften[].auftragsschluessel ab Fassung 1.8.

Oeffentliche Grenze: beleg_beurteilen. Form wie rechnungsauftrag
(ganz_passt), Bestand wie dokument_zu_auftragsschluessel.
"""

import copy

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
from tests.helpers.uebergabe import PARTNER_A, auftrag, beleg, schluesselpaar

SCHLUESSEL_A = "probe:lauf-1:autorin-a"
SCHLUESSEL_B = "probe:lauf-1:autor-b"


@pytest.fixture
def schluessel(tmp_path):
    return schluesselpaar(tmp_path / "schluessel")


class _Lage(Empfangslage):
    def __init__(self, dokumente=None):
        self._dokumente = dokumente or {}

    def partner_bekannt(self, partner_id: str) -> bool:
        return partner_id == PARTNER_A

    def dokument_zu_auftragsschluessel(self, schluessel: str):
        return self._dokumente.get(schluessel)


def _nutzlast_mit_schluesseln(*schluessel):
    nutzlast = auftrag()
    gutschriften = []
    for index, wert in enumerate(schluessel):
        eintrag = copy.deepcopy(nutzlast["gutschriften"][0])
        eintrag["auftragsschluessel"] = wert
        if index > 0:
            eintrag["beteiligter"]["partner_id"] = PARTNER_A
        gutschriften.append(eintrag)
    nutzlast["gutschriften"] = gutschriften
    return nutzlast


def _urteil(schluessel, nutzlast, lage=None):
    roh = beleg(schluessel[0], nutzlast)
    return beleg_beurteilen(
        roh, lage or _Lage(), schluessel_wurzel=schluessel[1],
    )


def test_gutschrift_ohne_auftragsschluessel_ist_pflichtfeld_fehlt(schluessel):
    nutzlast = _nutzlast_mit_schluesseln(SCHLUESSEL_A)
    del nutzlast["gutschriften"][0]["auftragsschluessel"]

    urteil = _urteil(schluessel, nutzlast)

    assert not urteil.angenommen
    assert [
        (f.code, f.pfad) for f in urteil.feststellungen
    ] == [("PFLICHTFELD_FEHLT", "$.nutzlast.gutschriften[0].auftragsschluessel")]


def test_gutschrift_auftragsschluessel_mit_zeilenende_ist_unbrauchbar(schluessel):
    nutzlast = _nutzlast_mit_schluesseln(SCHLUESSEL_A + "\n")

    urteil = _urteil(schluessel, nutzlast)

    assert not urteil.angenommen
    assert [
        (f.code, f.pfad) for f in urteil.feststellungen
    ] == [("WERT_UNBRAUCHBAR", "$.nutzlast.gutschriften[0].auftragsschluessel")]


def test_gutschrift_auftragsschluessel_schon_gerechnet(schluessel):
    nutzlast = _nutzlast_mit_schluesseln(SCHLUESSEL_A, SCHLUESSEL_B)
    lage = _Lage(dokumente={SCHLUESSEL_A: "Entwurf", SCHLUESSEL_B: "Entwurf"})

    urteil = _urteil(schluessel, nutzlast, lage=lage)

    assert not urteil.angenommen
    assert [
        (f.code, f.pfad, f.erhalten) for f in urteil.feststellungen
    ] == [
        ("AUFTRAG_SCHON_GERECHNET", "$.nutzlast.gutschriften[0].auftragsschluessel", "Entwurf"),
        ("AUFTRAG_SCHON_GERECHNET", "$.nutzlast.gutschriften[1].auftragsschluessel", "Entwurf"),
    ]


def test_gutschrift_auftragsschluessel_formgerecht_wird_angenommen(schluessel):
    nutzlast = _nutzlast_mit_schluesseln(SCHLUESSEL_A)

    urteil = _urteil(schluessel, nutzlast)

    assert urteil.angenommen, [f"{f.code} {f.pfad}" for f in urteil.feststellungen]
