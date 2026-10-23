"""Gemeinsames Lesen von `erwartung.json` fuer die Formatvektortests (#217).

Die Sollwerte stehen im Vektorordner, nicht in den Testdateien. Neue Vektoren
werden gemessen, sobald sie dort liegen; eine handgeschriebene Namensliste
waere wieder eine zweite Wahrheit.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from tests.helpers.formatvektoren import vektorordner

_VOR_NACH_01 = (
    "01_gueltig ist angenommen; gemessen wird dieser Beleg als naechster."
)
_VOR_NACH_01_MIT_DOKUMENT = (
    "01_gueltig ist angenommen; gemessen wird dieser Beleg als naechster. "
    "Zu seinem auftragsschluessel besteht ein nicht storniertes Dokument."
)
_VOR_SCHLUESSEL_FREI = (
    "Zum auftragsschluessel besteht kein nicht storniertes Dokument: "
    "Die Reihenfolge der Pruefungen ist frei (§ 11), sonst verdeckt "
    "AUFTRAG_SCHON_GERECHNET den Befund."
)
_VOR_PARTNER_UND_FREI = (
    "partner_id muss in den Stammdaten des Empfaengers liegen; zum "
    "auftragsschluessel darf kein nicht storniertes Dokument bestehen."
)
_VOR_BEIDE_PARTNER = (
    "Beide partner_id muessen in den Stammdaten des Empfaengers liegen."
)
_VOR_PARTNER_UNBEKANNT = (
    "Diese partner_id darf in den Stammdaten des Empfaengers NICHT liegen."
)
_VOR_PARTNER_UNBEKANNT_FREI = (
    f"{_VOR_PARTNER_UNBEKANNT} {_VOR_SCHLUESSEL_FREI}"
)


@dataclass(frozen=True)
class Lagebedarf:
    """Was die Empfangslage fuer einen Vektor herstellen muss."""

    nach_01: bool
    mit_dokument: bool


_BEKANNTE_VORAUSSETZUNGEN = {
    _VOR_NACH_01: Lagebedarf(nach_01=True, mit_dokument=False),
    _VOR_NACH_01_MIT_DOKUMENT: Lagebedarf(nach_01=True, mit_dokument=True),
    _VOR_SCHLUESSEL_FREI: Lagebedarf(nach_01=True, mit_dokument=False),
    _VOR_PARTNER_UND_FREI: Lagebedarf(nach_01=False, mit_dokument=False),
    _VOR_BEIDE_PARTNER: Lagebedarf(nach_01=False, mit_dokument=False),
    _VOR_PARTNER_UNBEKANNT: Lagebedarf(nach_01=True, mit_dokument=False),
    _VOR_PARTNER_UNBEKANNT_FREI: Lagebedarf(nach_01=True, mit_dokument=False),
}


def roh_laden(vektoren: Path) -> dict:
    """Liest erwartung.json; fehlende oder unlesbare Datei ist ein Fehler."""
    pfad = vektoren / "erwartung.json"
    if not pfad.is_file():
        raise AssertionError(
            f"keine lesbare Erwartung: {pfad} fehlt oder ist keine Datei"
        )
    try:
        roh = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"keine lesbare Erwartung: {pfad}: {exc}") from exc
    if not isinstance(roh, dict):
        raise AssertionError(f"keine lesbare Erwartung: {pfad} ist kein Objekt")
    return roh


def eintraege(vektoren: Path, gruppe: str) -> dict[str, dict]:
    """Name -> Eintrag einer Gruppe; jeder Eintrag braucht einen Namen."""
    roh = roh_laden(vektoren)
    if gruppe not in roh or not isinstance(roh[gruppe], list):
        raise AssertionError(
            f"keine lesbare Erwartung: Gruppe {gruppe!r} fehlt oder ist keine Liste"
        )
    ergebnis: dict[str, dict] = {}
    for eintrag in roh[gruppe]:
        if not isinstance(eintrag, dict) or "name" not in eintrag:
            raise AssertionError(
                f"keine lesbare Erwartung: Eintrag in {gruppe!r} ohne name"
            )
        ergebnis[eintrag["name"]] = eintrag
    return ergebnis


def namen(vektoren: Path, gruppe: str) -> list[str]:
    return sorted(eintraege(vektoren, gruppe))


def namen_beim_sammeln(gruppe: str) -> list[str]:
    """Namen zur pytest-Parametrisierung; leer, wenn kein Vektorordner da ist."""
    ordner = vektorordner()
    if ordner is None:
        return []
    return namen(ordner / "vektoren", gruppe)


def pruefe_vollstaendigkeit(vektoren: Path, gruppe: str) -> None:
    """Jede Vektordatei hat einen Eintrag und umgekehrt."""
    erwartet = set(eintraege(vektoren, gruppe))
    dateien = {p.stem for p in (vektoren / gruppe).glob("*.json")}
    if dateien != erwartet:
        raise AssertionError(
            f"vollstaendig: Dateien und erwartung.json fuer {gruppe!r} "
            f"weichen ab; nur Dateien={sorted(dateien - erwartet)}, "
            f"nur Erwartung={sorted(erwartet - dateien)}"
        )


def lagebedarf(voraussetzung: Optional[str]) -> Lagebedarf:
    """Wertet die Voraussetzung aus; Unbekanntes scheitert sichtbar."""
    if voraussetzung is None:
        return Lagebedarf(nach_01=True, mit_dokument=False)
    bedarf = _BEKANNTE_VORAUSSETZUNGEN.get(voraussetzung)
    if bedarf is None:
        raise AssertionError(
            f"Voraussetzung nicht unterstützt: {voraussetzung}"
        )
    return bedarf


def ist_angenommen(eintrag: dict) -> bool:
    """KEINE_ABLEHNUNG oder Gruppe ohne Befundcode (Umschlag, kanonisch)."""
    code = eintrag.get("erwarteter_code")
    if code is None:
        return True
    return code == "KEINE_ABLEHNUNG"


def erwarteter_code(eintrag: dict) -> str:
    """Befundcode des Eintrags; fehlt er, ist die Erwartung unlesbar."""
    if "erwarteter_code" not in eintrag:
        raise AssertionError(
            f"keine lesbare Erwartung: {eintrag.get('name')!r} ohne erwarteter_code"
        )
    return eintrag["erwarteter_code"]
