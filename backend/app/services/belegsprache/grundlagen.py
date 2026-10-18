from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

Belegsprache = Literal["de", "en"]

_PLATZHALTER = "\x00"


class UnknownDocumentLanguageError(ValueError):
    """Gespeicherter oder uebermittelter Sprachcode ist weder de noch en."""

    def __init__(self, wert):
        self.wert = wert
        super().__init__(f"Unbekannte Belegsprache: {wert!r}")


def resolve_belegsprache(wert: str | None) -> Belegsprache:
    """Nur `de` und `en`. Jeder andere Wert - inkl. None und leer - ist ein Fehler.

    Der Kompatibilitaetsdefault `de` fuer ein fehlendes Formularfeld liegt im
    Router vor dem Aufruf, nicht hier: ein bereits gespeicherter ungueltiger
    Wert darf nicht still auf Deutsch fallen.
    """
    if wert == "de" or wert == "en":
        return wert
    raise UnknownDocumentLanguageError(wert)


def betrag_roh(wert, nachkommastellen: int = 2) -> str:
    """Kaufmaennisch gerundete Zahl ohne Waehrung, mit englischen Trennzeichen."""
    zahl = wert if isinstance(wert, Decimal) else Decimal(str(wert))
    stufe = Decimal(1).scaleb(-nachkommastellen)
    zahl = zahl.quantize(stufe, rounding=ROUND_HALF_UP)
    return f"{zahl:,.{nachkommastellen}f}"


def betrag_de(wert, nachkommastellen: int = 2) -> str:
    return (
        betrag_roh(wert, nachkommastellen)
        .replace(",", _PLATZHALTER)
        .replace(".", ",")
        .replace(_PLATZHALTER, ".")
    )


def dezimal_klartext(wert) -> str:
    """`Decimal("60.0000")` -> `"60"`, `Decimal("61.5000")` -> `"61.5"`.

    Punkt, keine Tausender, nie Exponentenform. `str(x.normalize())` kippt bei
    durch zehn teilbaren Werten in `6E+1`; genau das stand am 2026-09-30 im
    Zahlenfeld des Rechnungsformulars.
    """
    zahl = wert if isinstance(wert, Decimal) else Decimal(str(wert))
    zahl = zahl.normalize()
    if zahl == zahl.to_integral_value():
        zahl = zahl.to_integral_value()
    return format(zahl, "f")
