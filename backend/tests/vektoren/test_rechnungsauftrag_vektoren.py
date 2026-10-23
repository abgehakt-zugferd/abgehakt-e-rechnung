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
"""

import hashlib
import json

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen

PARTNER_DES_PROBEBESTANDS = ("3f5b1c80-0000-4000-8000-00000000000c",)

ANGENOMMEN = ("01_gueltig", "02_zweiter_marktplatz")
ABGELEHNT = (
    "partner_id_unbekannt",
    "summe_grundlagen_weicht_ab",
    "summe_nicht_positiv",
    "steuerfeld",
    "anlagen_in_8a",
    "pflichtfeld_fehlt",
    "typcode_389",
    "waehrung_gbp",
    "zwei_monate",
    "gruppe_teilweise",
    "gruppe_unterbrochen",
    "bezeichnung_doppelt",
    "quelle_mit_plattformname",
    "auftragsschluessel_zeilenende",
    "netto_zeilenende",
)


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


def _erwartung(vektoren) -> dict:
    roh = json.loads((vektoren / "erwartung.json").read_text(encoding="utf-8"))
    return {e["name"]: e for e in roh["rechnungsauftraege"]}


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


def test_jeder_rechnungsauftragsvektor_ist_gemessen(vektoren):
    """Kein stilles Weglassen: jede Datei im Ordner kommt in einem Test vor,
    und jeder Name in erwartung.json hat eine Datei."""
    dateien = {p.stem for p in (vektoren / "rechnungsauftraege").glob("*.json")}
    assert dateien == set(_erwartung(vektoren))
    assert dateien == set(ANGENOMMEN) | set(ABGELEHNT) | {"auftrag_schon_gerechnet"}


@pytest.mark.parametrize("name", ANGENOMMEN)
def test_angenommener_rechnungsauftragsvektor_wird_angenommen(
    vektoren, schluesselordner, name,
):
    """erwartung.json ohne erwarteten Code: angenommen, Hash wie erwartet.

    `01_gueltig` ist der Kettenanfang (vorgaenger null) und braucht nur den
    Kunden im Stamm; `02_zweiter_marktplatz` ist der naechste nach ihm und
    beweist mit eigenem auftragsschluessel: Ein anderer Marktplatz im selben
    Monat ist ein eigener Auftrag, kein zweiter Haken zum selben."""
    eintrag = _erwartung(vektoren)[name]
    roh = (vektoren / "rechnungsauftraege" / f"{name}.json").read_bytes()
    lage = (
        Lage(partner=PARTNER_DES_PROBEBESTANDS)
        if name == "01_gueltig" else _lage_nach_dem_gueltigen(vektoren)
    )

    urteil = beleg_beurteilen(roh, lage, schluessel_wurzel=schluesselordner)

    assert urteil.angenommen, [f"{f.code} {f.pfad}" for f in urteil.feststellungen]
    assert urteil.feststellungen == ()
    assert urteil.beleg_sha256 == eintrag["beleg_sha256"]


@pytest.mark.parametrize("name", ABGELEHNT)
def test_abgelehnter_rechnungsauftragsvektor_trifft_seinen_befundcode(
    vektoren, schluesselordner, name,
):
    """erwartung.json mit erwartetem Code: GENAU dieser eine Befund."""
    eintrag = _erwartung(vektoren)[name]
    roh = (vektoren / "rechnungsauftraege" / f"{name}.json").read_bytes()

    urteil = beleg_beurteilen(
        roh, _lage_nach_dem_gueltigen(vektoren), schluessel_wurzel=schluesselordner,
    )

    assert not urteil.angenommen
    assert [f.code for f in urteil.feststellungen] == [eintrag["erwarteter_code"]]
    assert urteil.beleg_sha256 == eintrag["beleg_sha256"]


def test_zum_auftragsschluessel_gerechnet(vektoren, schluesselordner):
    """erwartung.json zu `auftrag_schon_gerechnet`: derselbe Schluessel wie
    `01_gueltig`, ein neuer Beleg (neue beleg_id). Der Befund nennt im
    erhalten das Dokument, das zu diesem Schluessel bereits besteht -
    'Entwurf', wie es erwartung.json beschreibt ('Rechnungsnummer oder
    Entwurf'): Die Rechnung selbst entsteht erst mit einem spaeteren
    Bauschritt."""
    eintrag = _erwartung(vektoren)["auftrag_schon_gerechnet"]
    roh = (vektoren / "rechnungsauftraege" / "auftrag_schon_gerechnet.json").read_bytes()
    schluessel = json.loads(roh)["nutzlast"]["auftragsschluessel"]

    urteil = beleg_beurteilen(
        roh,
        _lage_nach_dem_gueltigen(vektoren, dokumente={schluessel: "Entwurf"}),
        schluessel_wurzel=schluesselordner,
    )

    assert not urteil.angenommen
    assert [(f.code, f.pfad, f.erhalten) for f in urteil.feststellungen] == [
        ("AUFTRAG_SCHON_GERECHNET", "$.nutzlast.auftragsschluessel", "Entwurf"),
    ]
    assert urteil.beleg_sha256 == eintrag["beleg_sha256"]
