"""Wie Zahlen für Menschen geschrieben werden — genau einmal, für alle Wege.

Diese Regeln standen vorher doppelt im Programm: ausformuliert im
PDF-Generator (richtig) und als `{{ "%.2f"|format(...) }}` in vier Vorlagen
(falsch — C-Formatierung kennt weder Dezimalkomma noch Tausenderpunkt). Der
Bildschirm zeigte deshalb `2501.38 €`, während im erzeugten Beleg `2.501,38 €`
stand. Zwei Kopien einer Regel driften; hier war die zweite von Anfang an
daneben. Wer eine dritte Stelle braucht, importiert von hier — und schreibt die
Umwandlung nicht noch einmal auf.

Warum kein `locale.setlocale`: Das ist ein prozessweiter, nicht
thread-sicherer Zustand und setzt voraus, dass die passende Locale im Image
erzeugt wurde (im schlanken Debian-Basisimage ist sie es nicht). Die Regel für
deutsche Zahlen ist zu einfach, um dafür eine Umgebungsabhängigkeit einzugehen.
"""
from decimal import Decimal, ROUND_HALF_UP

from fastapi.templating import Jinja2Templates

# Ein Zwischenzeichen, das in keiner der beiden Rollen vorkommt: Erst wird der
# englische Tausenderpunkt geparkt, dann der Dezimalpunkt zum Komma, dann der
# geparkte Trenner zum Punkt. Ohne den Umweg überschreibt der zweite Austausch
# das Ergebnis des ersten.
_PLATZHALTER = "\x00"


def betrag(wert, nachkommastellen: int = 2) -> str:
    """`Decimal("2501.38")` → `"2.501,38"` — Zahl ohne Währungszeichen.

    Gibt es getrennt von `euro`, weil die Kennzahl-Kacheln der Übersicht die
    Zahl groß und das € klein daneben setzen; dort würde ein mitgeliefertes €
    doppelt stehen. `nachkommastellen=0` ist für ebendiese Kacheln gedacht:
    Cent sind dort Lärm.

    Nimmt `Decimal` (der Regelfall aus der Datenbank), `int` und `float`
    entgegen. `float` wird über `str()` eingelesen und nicht über
    `Decimal(float)` — sonst schleppt der Betrag die Binärungenauigkeit mit
    hinein (`Decimal(0.1)` ist nicht `Decimal("0.1")`).
    """
    zahl = wert if isinstance(wert, Decimal) else Decimal(str(wert))
    # Kaufmännisch runden. Pythons Standard ist ROUND_HALF_EVEN ("bankers
    # rounding") und würde 0,145 auf 0,14 abrunden — auf einer Rechnung ist das
    # nicht die erwartete Regel.
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
    return f"{betrag(wert)} €"


def menge(wert) -> str:
    """`Decimal("14.0000")` → `"14"`, `Decimal("2.5000")` → `"2,5"`.

    Die Spalte `quantity` steht in der Datenbank mit vier Nachkommastellen —
    das braucht, wer 0,25 Stunden abrechnet. Angezeigt gehören sie nur, wenn
    sie etwas bedeuten: `14.0000 Stunden` liest sich wie ein Messwert, nicht
    wie eine Position auf einer Rechnung.
    """
    zahl = wert if isinstance(wert, Decimal) else Decimal(str(wert))
    zahl = zahl.normalize()
    # `normalize()` macht aus 14.0000 die Exponentialform 1.4E+1; `to_integral_value`
    # holt sie zurück in die Festkommaform, sonst stünde "1.4E+1" auf der Seite.
    if zahl == zahl.to_integral_value():
        zahl = zahl.to_integral_value()
    return format(zahl, "f").replace(".", ",")


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
