"""Wie Zahlen für Menschen geschrieben werden — genau einmal, für alle Wege.

Diese Regeln standen vorher doppelt im Programm: ausformuliert im
PDF-Generator (richtig) und als `{{ "%.2f"|format(...) }}` in vier Vorlagen
(falsch — C-Formatierung kennt weder Dezimalkomma noch Tausenderpunkt). Der
Bildschirm zeigte deshalb `2501.38 €`, während im erzeugten Beleg `2.501,38 €`
stand. Zwei Kopien einer Regel driften; hier war die zweite von Anfang an
daneben. Wer eine dritte Stelle braucht, importiert von hier — und schreibt die
Umwandlung nicht noch einmal auf.

Die Beleg-PDF-Darstellung (auch Englisch) liegt in `services/belegsprache.py`.
Hier bleibt die deutsche UI-Darstellung; Betrag und Menge nutzen dieselbe
zustandsfreie Rechenregel wie `Belegdarstellung` für `de` (kein locale.setlocale).

Warum kein `locale.setlocale`: Das ist ein prozessweiter, nicht
thread-sicherer Zustand und setzt voraus, dass die passende Locale im Image
erzeugt wurde (im schlanken Debian-Basisimage ist sie es nicht). Die Regel für
deutsche Zahlen ist zu einfach, um dafür eine Umgebungsabhängigkeit einzugehen.
"""
from decimal import Decimal, ROUND_HALF_UP

from fastapi.templating import Jinja2Templates

from app.services.beleg_status import badge_klasse, etikett
from app.services.belegsprache import darstellung as beleg_darstellung

_DE = beleg_darstellung("de")
_PLATZHALTER = "\x00"


def betrag(wert, nachkommastellen: int = 2) -> str:
    """`Decimal("2501.38")` → `"2.501,38"` — Zahl ohne Währungszeichen.

    Gibt es getrennt von `euro`, weil die Kennzahl-Kacheln der Übersicht die
    Zahl groß und das € klein daneben setzen; dort würde ein mitgeliefertes €
    doppelt stehen. `nachkommastellen=0` ist für ebendiese Kacheln gedacht:
    Cent sind dort Lärm.

    Dieselbe kaufmännische Rundung und Trennzeichenregel wie Belegdarstellung.de,
    zusaetzlich mit waehlbaren Nachkommastellen fuer die UI-Kacheln.
    """
    zahl = wert if isinstance(wert, Decimal) else Decimal(str(wert))
    stufe = Decimal(1).scaleb(-nachkommastellen)
    zahl = zahl.quantize(stufe, rounding=ROUND_HALF_UP)
    return (
        f"{zahl:,.{nachkommastellen}f}"
        .replace(",", _PLATZHALTER)
        .replace(".", ",")
        .replace(_PLATZHALTER, ".")
    )


def euro(wert) -> str:
    """`Decimal("2501.38")` → `"2.501,38 €"`."""
    return _DE.format_betrag(wert)


def menge(wert) -> str:
    """`Decimal("14.0000")` → `"14"`, `Decimal("2.5000")` → `"2,5"`."""
    return _DE.format_menge(wert)


def registriere_darstellungsfilter(templates: Jinja2Templates) -> None:
    """Macht `|euro` und `|menge` in einem Jinja-Environment verfügbar.

    Muss JEDE Instanz einzeln bekommen: In diesem Projekt hält jeder Router
    sein eigenes Environment (dieselbe Lage wie bei
    `branding.register_branding_globals`). Ein hier vergessener Router fällt
    nicht beim Start auf, sondern erst beim Aufruf seiner Seite. Dagegen steht
    die Drift-Wache in `tests/test_geldformat.py`.
    """
    templates.env.filters["euro"] = euro
    templates.env.filters["betrag"] = betrag
    templates.env.filters["menge"] = menge
    templates.env.filters["beleg_etikett"] = etikett
    templates.env.filters["beleg_badge"] = badge_klasse
