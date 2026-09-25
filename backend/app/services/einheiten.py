"""Fester Einheitenkatalog (Option A): eine Quelle fuer Formular, Validator und CII.

Bezeichnung auf dem Beleg und UN/ECE-Code sind verschiedene Eigenschaften derselben
Einheit. Unbekannte Werte werden niemals zu Stueck umgedeutet. Recommendation 20
Revision 11e (Peppol BIS Billing 3.0, Mai 2026): Person/Personen/Persons → IE.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Einheit:
    key: str
    un_code: str
    bezeichnungen: tuple[str, ...]


class UnknownUnitError(ValueError):
    """Einheitenwert ist leer oder steht nicht im Katalog."""

    def __init__(self, wert: str):
        self.wert = wert
        super().__init__(f"Unbekannte Einheit: {wert!r}")


_KATALOG: tuple[Einheit, ...] = (
    Einheit("piece", "C62", ("Stück",)),
    Einheit("person", "IE", ("Person", "Personen", "Persons")),
    Einheit("hour", "HUR", ("Stunde", "Stunden")),
    Einheit("day", "DAY", ("Tag", "Tage")),
    Einheit("month", "MON", ("Monat", "Monate")),
    Einheit("kilometre", "KMT", ("Kilometer",)),
    Einheit("metre", "MTR", ("Meter",)),
    Einheit("kilogram", "KGM", ("kg",)),
    Einheit("litre", "LTR", ("Liter",)),
    Einheit("lump_sum", "LS", ("Pauschal", "Pauschale")),
)


def einheiten() -> tuple[Einheit, ...]:
    return _KATALOG


def formular_bezeichnungen() -> tuple[str, ...]:
    """Alle waehlbaren Bezeichnungen in Katalogreihenfolge (Formularoptionen)."""
    return tuple(b for e in einheiten() for b in e.bezeichnungen)


def resolve_einheit(wert: str) -> Einheit:
    """Exakter Vergleich nach aeusserem Trim; kein Default, keine Gross-/Kleinschreibung."""
    nadel = (wert or "").strip()
    if not nadel:
        raise UnknownUnitError(wert if wert is not None else "")
    for einheit in einheiten():
        if nadel in einheit.bezeichnungen:
            return einheit
    raise UnknownUnitError(nadel)


def unbekannte_bezeichnungen(werte: Iterable[str | None]) -> tuple[str, ...]:
    """Die Werte, die der Katalog nicht kennt, ohne Dubletten, in Eingabereihenfolge.

    Das Formular braucht sie als eigene Optionen: ein Altwert ohne Option geht beim
    naechsten Absenden lautlos verloren, und "Stück" stillschweigend einzusetzen waere
    die Umdeutung, die dieser Katalog gerade abstellt.
    """
    unbekannt: list[str] = []
    for wert in werte:
        nadel = (wert or "").strip()
        if not nadel or nadel in unbekannt:
            continue
        try:
            resolve_einheit(nadel)
        except UnknownUnitError:
            unbekannt.append(nadel)
    return tuple(unbekannt)
