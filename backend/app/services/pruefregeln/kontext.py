"""Der Pruefkontext: einmal aufgeloest, was mehrere Regeln brauchen.

validator.py liest Belegart, Kleinbetrag und Steuerkategorie EINMAL aus dem
Beleg und uebergibt das Ergebnis unveraenderlich an jede Regel; nichts wird
zweimal berechnet oder an zwei Stellen gelesen.
"""
from dataclasses import dataclass
from decimal import Decimal

from app.models.company import Company
from app.models.invoice import Invoice
from app.services.belegart import Belegart


@dataclass(frozen=True)
class Pruefkontext:
    invoice: Invoice
    company: Company
    # Roher invoice_type aus dem Modell; None = Standardrechnung (380).
    rechnungstyp: str | None
    # Aufgeloeste Belegart; None bei unbekanntem Typ (meldet belegbezug.py).
    belegart: Belegart | None
    # § 33 UStDV: Kleinbetrag bis einschliesslich 250 EUR brutto.
    kleinbetrag: bool
    # tax_category aus dem Modell, mit Modell-Default "S".
    steuerkategorie: str
    # Abzug auf Belegebene (BG-20): Betrag und Grund sind ein Paar.
    abzug_betrag: Decimal | None
    abzug_grund: str | None
