"""Kanonisierung, Hash und Umschlag eines Übergabebelegs (§§ 2, 3 UEBERGABEFORMAT).

Eigene Kanonisierung — nicht die des Absenders übernehmen. Gelesen und beurteilt
wird ein Beleg nur noch an EINER Stelle: `uebergabe_befund.beleg_beurteilen`
(ein Prüfpfad, abgehakt#159). Was dieser Pfad braucht, steht hier.
"""

import base64
import hashlib
import unicodedata

from app.services.protokoll import PROTOKOLL_VERSION

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
    """Ein Wert, den `kanonisch` ablehnt.

    Das ist keine Auskunft an den Absender: Der Befund samt Code entsteht in
    `uebergabe_befund.beleg_beurteilen` (der einzige Prüfpfad, abgehakt#159);
    hier wird nur die Probe gemacht, und wer keine Auskunft traegt, wirft.
    """


def _sortierschluessel(name: str) -> bytes:
    return unicodedata.normalize("NFC", name).encode("utf-16-be")


def _zeichenkette(wert: str) -> str:
    # § 3 Zusatz 1: Normalform NFC. RFC 8785 verlangt keine Normalisierung,
    # das Uebergabeformat tut es - derselbe Name in NFD und in NFC sind
    # verschiedene Bytes und derselbe Name, und sonst haengen Hash und
    # Signatur davon ab, ueber welches Dateisystem ein Name gelaufen ist
    # (macOS liefert routinemaessig NFD).
    wert = unicodedata.normalize("NFC", wert)
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


def kanonisierungsfehler(wert, praefix: str = "$"):
    """(pfad, wert) des ersten Werts, den `kanonisch` ablehnt, oder None.

    Die Ausnahme nennt keine Stelle; ein Befund, der den Absender informieren
    soll, aber schon. Gesucht wird in derselben Sortierung wie `kanonisch`,
    damit beide Stelle und Wert meinen.
    """
    try:
        _wert(wert)
        return None
    except UebergabeFehler:
        pass
    if isinstance(wert, dict):
        kinder = [
            (f"{praefix}.{name}", wert[name])
            for name in sorted(wert, key=_sortierschluessel)
        ]
    elif isinstance(wert, (list, tuple)):
        kinder = [
            (f"{praefix}[{nummer}]", eintrag)
            for nummer, eintrag in enumerate(wert)
        ]
    else:
        kinder = []
    for pfad, eintrag in kinder:
        fund = kanonisierungsfehler(eintrag, pfad)
        if fund is not None:
            return fund
    return praefix, wert


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
    format_version: str = FORMAT_VERSION,
) -> bytes:
    ohne_signatur = {
        "format_version": format_version,
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
