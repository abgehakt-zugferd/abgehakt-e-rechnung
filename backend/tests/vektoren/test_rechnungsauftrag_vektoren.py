"""Der Leser gegen die Vektoren der Gruppe rechnungsauftraege (§ 8a, 1.7).

Gemessen wird gegen die Bytes und die Sollwerte in `erwartung.json`; in
diesem Test steht kein abgeschriebener Befundcode. Ein Vektor mit
erwartetem Code trifft GENAU EINEN Befund - nur so ist bewiesen, dass nicht
zufaellig irgendeine fruehere Probe ihn abgewiesen hat. Ein Vektor ohne
erwarteten Code (KEINE_ABLEHNUNG) wird angenommen.

Die Kette: Jeder Vektor ausser `01_gueltig` nennt ihn als vorgaenger_hash
und ist eine Sekunde jünger erzeugt - gemessen wird jeder als der NAECHSTE
nach `01_gueltig`, nie in einer Kette untereinander. Der Bestand zu den
Auftragsschluesseln ist die leere Lage: Aus einem angenommenen Auftrag
entsteht noch kein Beleg. Nur `auftrag_schon_gerechnet` wird in einer Lage
gemessen, in der zu seinem Schluessel bereits ein Dokument besteht; welcher
Wert die Lage dazu nennt, beschreibt erwartung.json ('Rechnungsnummer oder
Entwurf') - gemessen wird 'Entwurf', denn weiter ist der Bestand dieses
Empfaengers fuer die Art noch nicht.

Die Fallliste kommt aus erwartung.json (#217), nicht aus einer Namensliste
in diesem Modul.
"""

import hashlib
import json

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
from tests.vektoren.erwartung_lesen import (
    eintraege,
    erwarteter_code,
    lagebedarf,
    namen_beim_sammeln,
    pruefe_vollstaendigkeit,
)

PARTNER_DES_PROBEBESTANDS = ("3f5b1c80-0000-4000-8000-00000000000c",)

_NAMEN = namen_beim_sammeln("rechnungsauftraege")


class Lage(Empfangslage):
    def __init__(self, zuletzt=None, kennungen=None, partner=(), dokumente=None):
        self._zuletzt = zuletzt
        self._kennungen = kennungen or {}
        self._partner = partner
        self._dokumente = dokumente or {}

    def zuletzt_angenommen(self, absender):
        return self._zuletzt

    def sha_zu_beleg_id(self, beleg_id):
        return self._kennungen.get(beleg_id)

    def partner_bekannt(self, partner_id):
        return partner_id in self._partner

    def dokument_zu_auftragsschluessel(self, schluessel):
        return self._dokumente.get(schluessel)


def _lage_nach_dem_gueltigen(vektoren, dokumente=None):
    """Die Lage, in der `01_gueltig` bereits angenommen wurde: Er ist der
    vorgaenger jedes weiteren Vektors der Gruppe, und seine Kennung ist
    gemerkt - derselbe Beleg noch einmal waere keine Ablehnung."""
    roh = (vektoren / "rechnungsauftraege" / "01_gueltig.json").read_bytes()
    beleg = json.loads(roh)
    from app.services.protokoll import zeit

    return Lage(
        zuletzt=(hashlib.sha256(roh).hexdigest(), zeit(beleg["erzeugt_am"])),
        kennungen={beleg["beleg_id"]: hashlib.sha256(roh).hexdigest()},
        partner=PARTNER_DES_PROBEBESTANDS,
        dokumente=dokumente,
    )


def _lage_fuer(vektoren, bedarf, roh):
    if not bedarf.nach_01:
        return Lage(partner=PARTNER_DES_PROBEBESTANDS)
    dokumente = None
    if bedarf.mit_dokument:
        schluessel = json.loads(roh)["nutzlast"]["auftragsschluessel"]
        dokumente = {schluessel: "Entwurf"}
    return _lage_nach_dem_gueltigen(vektoren, dokumente=dokumente)


def test_jeder_rechnungsauftragsvektor_ist_gemessen(vektoren):
    """Kein stilles Weglassen: jede Datei im Ordner kommt in einem Test vor,
    und jeder Name in erwartung.json hat eine Datei."""
    pruefe_vollstaendigkeit(vektoren, "rechnungsauftraege")


@pytest.mark.parametrize("name", _NAMEN)
def test_rechnungsauftragsvektor_trifft_seine_erwartung(
    vektoren, schluesselordner, name,
):
    """Soll aus erwartung.json: angenommen, genau ein Befund, oder schon gerechnet."""
    eintrag = eintraege(vektoren, "rechnungsauftraege")[name]
    bedarf = lagebedarf(eintrag.get("voraussetzung"))
    roh = (vektoren / "rechnungsauftraege" / f"{name}.json").read_bytes()
    lage = _lage_fuer(vektoren, bedarf, roh)

    urteil = beleg_beurteilen(roh, lage, schluessel_wurzel=schluesselordner)
    erwartet = erwarteter_code(eintrag)

    if erwartet == "KEINE_ABLEHNUNG":
        assert urteil.angenommen, [f"{f.code} {f.pfad}" for f in urteil.feststellungen]
        assert urteil.feststellungen == ()
    elif erwartet == "AUFTRAG_SCHON_GERECHNET":
        # erwartung.json: 'Rechnungsnummer oder Entwurf' - gemessen wird Entwurf.
        assert not urteil.angenommen
        assert [(f.code, f.pfad, f.erhalten) for f in urteil.feststellungen] == [
            ("AUFTRAG_SCHON_GERECHNET", "$.nutzlast.auftragsschluessel", "Entwurf"),
        ]
    else:
        assert not urteil.angenommen
        assert [f.code for f in urteil.feststellungen] == [erwartet]
    assert urteil.beleg_sha256 == eintrag["beleg_sha256"]
