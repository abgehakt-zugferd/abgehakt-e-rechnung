"""Übergabebelege lesen und prüfen (§§ 2, 4, 5, 6 UEBERGABEFORMAT).

Eigene Kanonisierung — nicht die des Absenders übernehmen.
"""

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from cryptography.exceptions import InvalidSignature

from app.services.protokoll import PROTOKOLL_VERSION, fassung_annehmbar
from app.services.uebergabe_schluessel import schluessel_laden

# Die Fassung, die diese Anwendung beherrscht und in eigene Umschlaege schreibt.
# Sie steht in app/services/protokoll.py, weil sie dort gegen das Protokoll der
# Uebergabepapiere gemessen wird (abgehakt#72) und nicht an der Stelle erfunden
# werden darf, die sie braucht.
FORMAT_VERSION = PROTOKOLL_VERSION
VERFAHREN = "Ed25519"
ABSENDER_TANTIEMEN = "tantiemen-app"
EMPFAENGER_ABGEHAKT = "abgehakt"

_STEUERZEICHEN = {
    "\b": "\\b", "\t": "\\t", "\n": "\\n", "\f": "\\f", "\r": "\\r",
    '"': '\\"', "\\": "\\\\",
}


class UebergabeFehler(ValueError):
    """Ein Beleg, den dieser Empfänger nicht annehmen kann.

    `CODE` ist der Befund aus dem geschlossenen Wertevorrat des Protokolls; er
    ist später der Inhalt der Quittung (§ 10) und deshalb hier und nicht in der
    Darstellung. Die Basis trägt keinen: wer keinen Code nennen kann, hat keinen
    Befund, sondern eine Ausnahme.
    """

    CODE = ""


class FassungUnvertraeglich(UebergabeFehler):
    """§ 2: format_version mit höherem major, oder gar keine Fassungsangabe."""

    CODE = "FASSUNG_UNVERTRAEGLICH"


class SignaturUngueltig(UebergabeFehler):
    """Die Bytes sind nicht die, die signiert wurden."""

    CODE = "SIGNATUR_UNGUELTIG"


def _sortierschluessel(name: str) -> bytes:
    return name.encode("utf-16-be")


def _zeichenkette(wert: str) -> str:
    teile = ['"']
    for zeichen in wert:
        if zeichen in _STEUERZEICHEN:
            teile.append(_STEUERZEICHEN[zeichen])
        elif ord(zeichen) < 0x20:
            teile.append(f"\\u{ord(zeichen):04x}")
        else:
            teile.append(zeichen)
    teile.append('"')
    return "".join(teile)


def _wert(wert) -> str:
    if wert is None:
        return "null"
    if wert is True:
        return "true"
    if wert is False:
        return "false"
    if isinstance(wert, str):
        return _zeichenkette(wert)
    if isinstance(wert, int):
        return str(wert)
    if isinstance(wert, float):
        raise UebergabeFehler("Gleitkommazahl in einem Übergabebeleg")
    if isinstance(wert, (list, tuple)):
        return "[" + ",".join(_wert(e) for e in wert) + "]"
    if isinstance(wert, dict):
        paare = (
            f"{_zeichenkette(str(k))}:{_wert(wert[k])}"
            for k in sorted(wert, key=_sortierschluessel)
        )
        return "{" + ",".join(paare) + "}"
    raise UebergabeFehler(f"Nicht kanonisierbar: {type(wert).__name__}")


def kanonisch(wert) -> bytes:
    return _wert(wert).encode("utf-8")


def sha256_hex(daten: bytes) -> str:
    return hashlib.sha256(daten).hexdigest()


def umschlag(
    *,
    nutzlast,
    nutzlast_art: str,
    beleg_id: str,
    erzeugt_am: str,
    absender: str,
    empfaenger: str,
    vorgaenger_hash: str | None,
    schluessel_id: str,
    signierer,
) -> bytes:
    ohne_signatur = {
        "format_version": FORMAT_VERSION,
        "beleg_id": beleg_id,
        "nutzlast_art": nutzlast_art,
        "absender": absender,
        "empfaenger": empfaenger,
        "erzeugt_am": erzeugt_am,
        "vorgaenger_hash": vorgaenger_hash,
        "nutzlast_sha256": sha256_hex(kanonisch(nutzlast)),
        "nutzlast": nutzlast,
    }
    signatur = signierer(kanonisch(ohne_signatur))
    return kanonisch({
        **ohne_signatur,
        "signatur": {
            "verfahren": VERFAHREN,
            "schluessel_id": schluessel_id,
            "wert": base64.b64encode(signatur).decode("ascii"),
        },
    })


@dataclass(frozen=True)
class Belegbefund:
    beleg_id: str
    absender: str
    empfaenger: str
    format_version: str
    nutzlast_art: str
    erzeugt_am: datetime
    vorgaenger_hash: Optional[str]
    schluessel_id: str
    signatur_gueltig: bool
    nutzlast: dict


def _zeit(wert: str) -> datetime:
    return datetime.fromisoformat(wert.replace("Z", "+00:00"))


def beleg_pruefen(roh: bytes, wurzel: Optional[Path] = None) -> Belegbefund:
    beleg = json.loads(roh.decode("utf-8"))

    fassung = beleg.get("format_version")
    if not fassung_annehmbar(fassung):
        raise FassungUnvertraeglich(str(fassung))

    nutzlast = beleg["nutzlast"]
    if hashlib.sha256(kanonisch(nutzlast)).hexdigest() != beleg["nutzlast_sha256"]:
        raise SignaturUngueltig("nutzlast_sha256 passt nicht zur Nutzlast")

    ohne_signatur = {k: v for k, v in beleg.items() if k != "signatur"}
    signatur = beleg["signatur"]
    erzeugt_am = _zeit(beleg["erzeugt_am"])
    schluessel = schluessel_laden(
        beleg["absender"], signatur["schluessel_id"], erzeugt_am, wurzel=wurzel,
    )
    try:
        schluessel.verify(
            base64.b64decode(signatur["wert"]),
            kanonisch(ohne_signatur),
        )
    except InvalidSignature as fehler:
        raise SignaturUngueltig(beleg.get("beleg_id", "?")) from fehler

    return Belegbefund(
        beleg_id=beleg["beleg_id"],
        absender=beleg["absender"],
        empfaenger=beleg["empfaenger"],
        format_version=fassung,
        nutzlast_art=beleg["nutzlast_art"],
        erzeugt_am=erzeugt_am,
        vorgaenger_hash=beleg.get("vorgaenger_hash"),
        schluessel_id=signatur["schluessel_id"],
        signatur_gueltig=True,
        nutzlast=nutzlast,
    )


@dataclass(frozen=True)
class Kettenbefund:
    laenge: int
    lueckenlos: bool
    erster_ohne_vorgaenger: bool
    bruch_bei: Optional[str]


def kette_pruefen(pfade: Sequence[Path]) -> Kettenbefund:
    vorheriger_hash = None
    bruch = None
    erster_ohne_vorgaenger = True

    for nummer, pfad in enumerate(pfade):
        roh = Path(pfad).read_bytes()
        beleg = json.loads(roh.decode("utf-8"))
        genannt = beleg.get("vorgaenger_hash")
        if nummer == 0:
            erster_ohne_vorgaenger = genannt is None
        elif genannt != vorheriger_hash and bruch is None:
            bruch = Path(pfad).name
        vorheriger_hash = hashlib.sha256(roh).hexdigest()

    return Kettenbefund(
        len(pfade), bruch is None, erster_ohne_vorgaenger, bruch,
    )
