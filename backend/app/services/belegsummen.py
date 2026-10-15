"""Belegsummen mit optionalem Abzug auf Belagebene (EN 16931 BG-20).

Diese Funktion ist die einzige Stelle, an der Positionssumme, Abzug,
Steuerbasis, Steuer und Brutto eines Belegs gerechnet werden. Ohne Abzug
werden die Positionssteuern aufsummiert statt neu gerechnet, weil jede
Position einzeln auf Cent gerundet ist; eine Neurechnung auf der Summe
wuerde bestehende Belege nachtraeglich um Centbetrage veraendern.
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Belegsummen:
    """Rechnungssummen eines Belegs, alle Betraege auf 0.01 gerundet."""

    positionen_netto: Decimal
    abzug: Decimal
    steuerbasis: Decimal
    steuer: Decimal
    brutto: Decimal


def belegsummen(positionen, abzug_betrag: Decimal | None) -> Belegsummen:
    """Summiert Positionen; optional wird ein Nettobetrag abgezogen (BG-20).

    Ohne Abzug ist die Steuer die Summe der Positionssteuern. Mit Abzug wird
    die Steuer auf der verminderten Basis neu gerechnet; dafuer muessen alle
    Positionen denselben Steuersatz tragen.
    """
    positionen_netto = sum(
        (p.net_amount for p in positionen), Decimal("0"),
    ).quantize(_CENT, rounding=ROUND_HALF_UP)

    if abzug_betrag is None:
        abzug = Decimal("0.00")
        steuerbasis = positionen_netto
        steuer = sum(
            (p.tax_amount for p in positionen), Decimal("0"),
        ).quantize(_CENT, rounding=ROUND_HALF_UP)
    else:
        abzug = Decimal(abzug_betrag).quantize(_CENT, rounding=ROUND_HALF_UP)
        if not positionen:
            raise ValueError("Abzug ohne Positionen ist unzulaessig.")
        if abzug <= 0:
            raise ValueError("Abzug muss positiv sein.")
        saetze = {p.tax_rate for p in positionen}
        if len(saetze) > 1:
            raise ValueError(
                "Abzug setzt einen einheitlichen Steuersatz voraus.",
            )
        if abzug >= positionen_netto:
            raise ValueError("Abzug muss kleiner als die Positionssumme sein.")
        steuerbasis = (positionen_netto - abzug).quantize(
            _CENT, rounding=ROUND_HALF_UP,
        )
        steuer = (
            steuerbasis * saetze.pop() / Decimal("100")
        ).quantize(_CENT, rounding=ROUND_HALF_UP)

    brutto = (steuerbasis + steuer).quantize(_CENT, rounding=ROUND_HALF_UP)
    return Belegsummen(
        positionen_netto=positionen_netto,
        abzug=abzug,
        steuerbasis=steuerbasis,
        steuer=steuer,
        brutto=brutto,
    )
