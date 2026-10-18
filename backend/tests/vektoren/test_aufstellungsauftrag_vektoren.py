"""Der Leser gegen die Vektoren der Gruppe aufstellungen (§ 8b, 1.7).

Gemessen wird gegen die Bytes und die Sollwerte in `erwartung.json`; in
diesem Test steht kein abgeschriebener Befundcode. Ein Vektor mit
erwartetem Code trifft GENAU EINEN Befund - nur so ist bewiesen, dass nicht
zufaellig irgendeine fruehere Probe ihn abgewiesen hat. Ein Vektor ohne
erwarteten Code (KEINE_ABLEHNUNG) wird angenommen.

Die Kette: Jeder Vektor ausser `01_gueltig` nennt ihn als vorgaenger_hash
und ist eine Sekunde junger erzeugt - gemessen wird jeder als der NAECHSTE
nach `01_gueltig`, nie in einer Kette untereinander. Der Bestand zu den
Auftragsschluesseln ist die leere Lage; nur `auftrag_schon_gerechnet`
wird in einer Lage gemessen, in der zu seinem Schluessel bereits ein
Dokument besteht ('Entwurf', wie erwartung.json es beschreibt).

Die Anlagen liegen unter aufstellungen/anlagen/ als <sha256>.xlsx, lesend
eingehaengt; nichts davon landet im Repositorium. Eine der Dateien traegt
absichtlich einen Namen, der nicht zu ihrem Inhalt passt - genau die
macht `anlage_inhalt_falsch` messbar. Der Leser oeffnet keine xlsx: Er
prueft Hash und Groesse der Bytes.
"""

import hashlib
import json

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen

PARTNER_DES_PROBEBESTANDS = ("3f5b1c80-0000-4000-8000-00000000000d",)

ANGENOMMEN = ("01_gueltig",)
ABGELEHNT = (
    "partner_id_unbekannt",
    "betraege_gehen_nicht_auf",
    "quellensteuer_negativ",
    "umrechnung_fehlt",
    "umrechnung_bei_euro",
    "typcode",
    "zahlungsnummer_gleitkomma",
    "waehrung_klein",
    "nur_eine_anlage",
    "medientyp_pdf",
    "anlage_fehlt",
    "anlage_groesse_falsch",
    "anlage_inhalt_falsch",
)


class Lage(Empfangslage):
    """Die Empfangslage der Messung: Kette, Kennung, Stamm - und die
    Anlagen aus dem Unterordner anlagen/ (§ 8b: Die Anlage liegt unter
    anlagen/<sha256>.xlsx, VOR dem Beleg geschrieben)."""

    def __init__(self, anlagen_ordner, zuletzt=None, kennungen=None,
                 partner=(), dokumente=None):
        self._anlagen_ordner = anlagen_ordner
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

    def anlagen_bytes(self, sha256):
        datei = self._anlagen_ordner / f"{sha256}.xlsx"
        return datei.read_bytes() if datei.is_file() else None


def _erwartung(vektoren) -> dict:
    roh = json.loads((vektoren / "erwartung.json").read_text(encoding="utf-8"))
    return {e["name"]: e for e in roh["aufstellungen"]}


def _lage_nach_dem_gueltigen(vektoren, dokumente=None):
    """Die Lage, in der `01_gueltig` bereits angenommen wurde: Er ist der
    vorgaenger jedes weiteren Vektors der Gruppe, und seine Kennung ist
    gemerkt - derselbe Beleg noch einmal waere keine Ablehnung."""
    roh = (vektoren / "aufstellungen" / "01_gueltig.json").read_bytes()
    beleg = json.loads(roh)
    from app.services.protokoll import zeit

    return Lage(
        vektoren / "aufstellungen" / "anlagen",
        zuletzt=(hashlib.sha256(roh).hexdigest(), zeit(beleg["erzeugt_am"])),
        kennungen={beleg["beleg_id"]: hashlib.sha256(roh).hexdigest()},
        partner=PARTNER_DES_PROBEBESTANDS,
        dokumente=dokumente,
    )


def test_jeder_aufstellungsvektor_ist_gemessen(vektoren):
    """Kein stilles Weglassen: jede Datei im Ordner kommt in einem Test vor,
    und jeder Name in erwartung.json hat eine Datei."""
    dateien = {p.stem for p in (vektoren / "aufstellungen").glob("*.json")}
    assert dateien == set(_erwartung(vektoren))
    assert dateien == set(ANGENOMMEN) | set(ABGELEHNT) | {"auftrag_schon_gerechnet"}


@pytest.mark.parametrize("name", ANGENOMMEN)
def test_angenommener_aufstellungsvektor_wird_angenommen(
    vektoren, schluesselordner, name,
):
    """erwartung.json ohne erwarteten Code: angenommen, Hash wie erwartet.

    `01_gueltig` ist der Kettenanfang (vorgaenger null); sein Partner steht
    im Stamm, seine beiden Anlagen liegen unter ihrem Hash, und die
    umrechnung steht, weil die waehrung USD ist."""
    eintrag = _erwartung(vektoren)[name]
    roh = (vektoren / "aufstellungen" / f"{name}.json").read_bytes()
    lage = Lage(vektoren / "aufstellungen" / "anlagen",
                partner=PARTNER_DES_PROBEBESTANDS)

    urteil = beleg_beurteilen(roh, lage, schluessel_wurzel=schluesselordner)

    assert urteil.angenommen, [f"{f.code} {f.pfad}" for f in urteil.feststellungen]
    assert urteil.feststellungen == ()
    assert urteil.beleg_sha256 == eintrag["beleg_sha256"]


@pytest.mark.parametrize("name", ABGELEHNT)
def test_abgelehnter_aufstellungsvektor_trifft_seinen_befundcode(
    vektoren, schluesselordner, name,
):
    """erwartung.json mit erwartetem Code: GENAU dieser eine Befund."""
    eintrag = _erwartung(vektoren)[name]
    roh = (vektoren / "aufstellungen" / f"{name}.json").read_bytes()

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
    Entwurf'): Mehr als ein Entwurf entsteht aus einer Aufstellung nicht."""
    eintrag = _erwartung(vektoren)["auftrag_schon_gerechnet"]
    roh = (vektoren / "aufstellungen" / "auftrag_schon_gerechnet.json").read_bytes()
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
