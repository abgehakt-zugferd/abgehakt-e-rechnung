"""Optionale Zusatzangaben einer Rechnungsposition.

Mengen, Preise und Einheit haben ihre eigenen Wege (Berechnung, Einheitenkatalog).
Was darüber hinaus an einer Position hängt, läuft durch vier Stationen: Formular
lesen, für Bearbeiten und Vorlage zurückgeben, beim Storno kopieren. Jede Station
hatte ihre eigene Feldliste, und ein neues Feld ging an jeder einzeln verloren.
Hier steht die Liste einmal.

Derzeit: Artikelnummer (BT-155).
"""
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
    return {"artikelnummer": artikelnummer or None}


def fuer_formular(item) -> dict:
    """Spalten einer gespeicherten Position → Werte für das Alpine-Formular."""
    return {"artikelnummer": item.artikelnummer or ""}


def kopie(item) -> dict:
    """Spalten, die eine Storno-Position von ihrem Original übernimmt."""
    return {"artikelnummer": item.artikelnummer}
