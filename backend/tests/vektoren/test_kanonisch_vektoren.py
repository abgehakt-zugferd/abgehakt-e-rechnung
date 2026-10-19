"""Die kanonische Form gegen die Formatvektoren (abgehakt#169).

Die Gruppe `kanonisch` in erwartung.json faellt die Faelle, an denen sich zwei
Umsetzungen der kanonischen Form scheiden - jede Anwendung misst in der eigenen
Suite gegen dieselben Bytes. Gemessen wird `uebergabebeleg.kanonisch` am Sollhash
aus erwartung.json und an den Sollbytes der `.kanonisch`-Datei; in diesem Test
steht kein abgeschriebener Hash.

Darunter ist `nfd_wird_nfc`: § 3 Zusatz 1 verlangt Normalform NFC, RFC 8785
alleine nicht. macOS liefert Namen routinemaessig in NFD; wer hier nicht
normalisiert, haengt mit Hash und Signatur davon ab, ueber welches Dateisystem
ein Name gelaufen ist.
"""

import hashlib
import json

import pytest

from app.services.uebergabebeleg import kanonisch

NAMEN = (
    "schluesselordnung",
    "nfd_wird_nfc",
    "nfc_bleibt_nfc",
    "geld_ist_zeichenkette",
    "null_ist_kettenanfang",
    "steuerzeichen",
    "verschachtelt",
    "ganzzahlen",
)


def _erwartung(vektoren) -> dict:
    roh = json.loads((vektoren / "erwartung.json").read_text(encoding="utf-8"))
    return {eintrag["name"]: eintrag for eintrag in roh["kanonisch"]}


def test_jeder_kanonisch_vektor_ist_gemessen(vektoren):
    """Kein stilles Weglassen: jede Datei im Ordner kommt in einem Test vor."""
    dateien = {p.stem for p in (vektoren / "kanonisch").glob("*.json")}
    assert dateien == set(_erwartung(vektoren))
    assert dateien == set(NAMEN)


@pytest.mark.parametrize("name", NAMEN)
def test_der_leser_trifft_sollbytes_und_sollhash(vektoren, name):
    """Der Vektor .json geht durch kanonisch() und muss die .kanonisch-Bytes
    treffen - byteweise und im Hash, sonst ist diese Umsetzung eine andere."""
    eintrag = _erwartung(vektoren)[name]
    roh = (vektoren / "kanonisch" / f"{name}.json").read_bytes()
    soll = (vektoren / "kanonisch" / f"{name}.kanonisch").read_bytes()

    ist = kanonisch(json.loads(roh.decode("utf-8")))

    assert ist == soll
    assert hashlib.sha256(ist).hexdigest() == eintrag["sha256"]
    assert len(ist) == eintrag["bytes"]


def test_nfd_und_nfc_desselben_namens_sind_dieselben_bytes(vektoren):
    """§ 3 Zusatz 1 ist die Regel selbst, nicht ihr Nebenprodukt: Die NFD- und
    die NFC-Schreibweise desselben Namens kanonisieren identisch - derselbe
    Hash, wie es erwartung.json fuer beide Vektoren verlangt."""
    nfd = (vektoren / "kanonisch" / "nfd_wird_nfc.json").read_bytes()
    nfc = (vektoren / "kanonisch" / "nfc_bleibt_nfc.json").read_bytes()

    assert kanonisch(json.loads(nfd.decode("utf-8"))) == kanonisch(
        json.loads(nfc.decode("utf-8"))
    )
