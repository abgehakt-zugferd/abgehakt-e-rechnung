"""Optionale Zusatzangaben einer Rechnungsposition.

Mengen, Preise und Einheit haben ihre eigenen Wege (Berechnung, Einheitenkatalog).
Was darüber hinaus an einer Position hängt, läuft durch vier Stationen: Formular
lesen, für Bearbeiten und Vorlage zurückgeben, beim Storno kopieren. Jede Station
hatte ihre eigene Feldliste, und ein neues Feld ging an jeder einzeln verloren.
Hier steht die Liste einmal.

Derzeit: Artikelnummer (BT-155) und Leistungszeitraum (BT-134/135).
"""
import unicodedata
from datetime import date

ARTIKELNUMMER_MAX = 50


class PositionsangabeUngueltig(ValueError):
    """Eingabe einer Position, die nicht gespeichert werden darf; Text ist für Menschen."""


def aus_formular(roh: dict, nr: int) -> dict:
    """Formularwerte einer Position → Spalten für `InvoiceItem`.

    `nr` ist die Positionsnummer für die Meldung. Fehlende Schlüssel sind erlaubt:
    ältere Formulare und Übergaben kennen die Felder nicht.
    """
    artikelnummer = str(roh.get("artikelnummer") or "").strip()
    if len(artikelnummer) > ARTIKELNUMMER_MAX:
        raise PositionsangabeUngueltig(
            f"Position {nr}: Artikelnummer ist länger als {ARTIKELNUMMER_MAX} Zeichen."
        )
    if not _einzeilig_und_xml_tauglich(artikelnummer):
        raise PositionsangabeUngueltig(
            f"Position {nr}: Artikelnummer darf keine Steuerzeichen oder Zeilenumbrüche enthalten."
        )
    von, bis = _zeitraum(roh, nr)
    return {"artikelnummer": artikelnummer or None, "leistung_von": von, "leistung_bis": bis}


def _zeitraum(roh: dict, nr: int) -> tuple[date | None, date | None]:
    """Beide oder keiner, Beginn nicht nach Ende. Strenger als BR-30, das auch nur
    eine Grenze zuließe: ein halber Zeitraum ist auf einer Rechnung eher ein
    Tippfehler als eine Absicht. Die Datenbank prüft dasselbe noch einmal."""
    try:
        von = _datum(roh.get("leistung_von"))
        bis = _datum(roh.get("leistung_bis"))
    except ValueError:
        raise PositionsangabeUngueltig(
            f"Position {nr}: Leistungszeitraum ist kein gültiges Datum."
        ) from None
    if (von is None) != (bis is None):
        raise PositionsangabeUngueltig(
            f"Position {nr}: Leistungszeitraum braucht Beginn und Ende."
        )
    if von and bis and von > bis:
        raise PositionsangabeUngueltig(
            f"Position {nr}: Leistungszeitraum beginnt nach seinem Ende."
        )
    return von, bis


def _datum(wert) -> date | None:
    text = str(wert or "").strip()
    return date.fromisoformat(text) if text else None


def _einzeilig_und_xml_tauglich(text: str) -> bool:
    """Keine Steuerzeichen (Kategorie Cc, darunter NUL, Tab, Umbruch), keine
    Surrogate und keine Nichtzeichen U+FFFE/U+FFFF: sie machen die XML ungültig,
    scheitern an PostgreSQL oder stehen im PDF anders als in der XML."""
    return not any(
        unicodedata.category(z) in ("Cc", "Cs") or z in "\ufffe\uffff" for z in text
    )


def fuer_formular(item, *, vorlage: bool = False) -> dict:
    """Spalten einer gespeicherten Position → Werte für das Alpine-Formular.

    `vorlage`: die Position wird Teil einer NEUEN Rechnung. Ihr Zeitraum gehört
    zur alten und fällt weg; verschoben wird nicht, weil der Rhythmus unbekannt ist.
    """
    zeitraum = not vorlage
    return {
        "artikelnummer": item.artikelnummer or "",
        "leistung_von": item.leistung_von.isoformat() if zeitraum and item.leistung_von else "",
        "leistung_bis": item.leistung_bis.isoformat() if zeitraum and item.leistung_bis else "",
    }


def kopie(item) -> dict:
    """Spalten, die eine Storno-Position von ihrem Original übernimmt."""
    return {
        "artikelnummer": item.artikelnummer,
        "leistung_von": item.leistung_von,
        "leistung_bis": item.leistung_bis,
    }
