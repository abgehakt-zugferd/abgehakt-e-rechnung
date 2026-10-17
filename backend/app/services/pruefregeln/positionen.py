"""§ 14 Abs. 4 Nr. 5 UStG – Leistungsbeschreibung und Positionen.

Je Position erst die Feldpruefungen, dann die Betragspruefungen; die Tests
pruefen Befund-Listen, diese Reihenfolge ist Vertragsbestandteil.
"""
from decimal import Decimal, ROUND_HALF_UP

from app.services.einheiten import UnknownUnitError, resolve_einheit
from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext

VALID_TAX_RATES = {Decimal("0"), Decimal("7"), Decimal("19")}


def pruefe_positionen(kontext: Pruefkontext) -> list[Issue]:
    items = kontext.invoice.items
    if not items:
        return [Issue("NO_ITEMS", "error", "Keine Rechnungspositionen vorhanden.", "items")]
    befunde: list[Issue] = []
    for item in items:
        befunde.extend(_pruefe_felder(kontext, item))
        befunde.extend(_pruefe_betraege(kontext, item))
    return befunde


def _pruefe_felder(kontext: Pruefkontext, item) -> list[Issue]:
    befunde: list[Issue] = []
    if not item.description or not item.description.strip():
        befunde.append(Issue(
            "ITEM_DESCRIPTION_MISSING", "error",
            f"Position {item.position}: Leistungsbeschreibung fehlt.", f"items[{item.position}].description"
        ))
    if item.quantity <= 0:
        befunde.append(Issue(
            "ITEM_QUANTITY_INVALID", "error",
            f"Position {item.position}: Menge muss größer als 0 sein.", f"items[{item.position}].quantity"
        ))
    try:
        resolve_einheit(item.unit if item.unit is not None else "")
    except UnknownUnitError:
        befunde.append(Issue(
            "UNIT_UNKNOWN", "error",
            f"Position {item.position}: unbekannte Einheit {(item.unit or '')!r}.",
            f"items[{item.position}].unit",
        ))
    if item.unit_price < 0:
        befunde.append(Issue(
            "ITEM_PRICE_NEGATIVE", "error",
            f"Position {item.position}: Negativer Einzelpreis ist nicht erlaubt.", f"items[{item.position}].unit_price"
        ))
    if item.unit_price == 0 and kontext.belegart is not None and kontext.belegart.intern == "self_billing":
        befunde.append(Issue(
            "ITEM_PRICE_ZERO", "error",
            f"Position {item.position}: Einzelpreis muss bei einer Honorargutschrift größer als 0 sein.",
            f"items[{item.position}].unit_price",
        ))
    return befunde


def _pruefe_betraege(kontext: Pruefkontext, item) -> list[Issue]:
    befunde: list[Issue] = []
    rate = item.tax_rate.quantize(Decimal("0"))
    if rate not in VALID_TAX_RATES:
        befunde.append(Issue(
            "TAX_RATE_INVALID", "error",
            f"Position {item.position}: Steuersatz {item.tax_rate}% ist ungültig. Erlaubt: 0%, 7%, 19%.",
            f"items[{item.position}].tax_rate"
        ))

    # Betragsprüfung je Position
    expected_net = (item.quantity * item.unit_price).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if abs(item.net_amount - expected_net) > Decimal("0.02"):
        befunde.append(Issue(
            "ITEM_AMOUNT_MISMATCH", "error",
            f"Position {item.position}: Nettobetrag {item.net_amount} stimmt nicht (erwartet {expected_net}).",
            f"items[{item.position}].net_amount"
        ))
    expected_tax = (item.net_amount * item.tax_rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    if abs(item.tax_amount - expected_tax) > Decimal("0.02"):
        befunde.append(Issue(
            "ITEM_TAX_MISMATCH", "error",
            f"Position {item.position}: Steuerbetrag {item.tax_amount} stimmt nicht (erwartet {expected_tax}).",
            f"items[{item.position}].tax_amount"
        ))
    if kontext.steuerkategorie in {"AE", "K"} and item.tax_amount != Decimal("0"):
        befunde.append(Issue(
            "TAX_AMOUNT_MUST_BE_ZERO", "error",
            f"Position {item.position}: Bei Reverse Charge / innergemeinschaftlicher "
            f"Lieferung muss der Steuerbetrag exakt 0,00 € betragen "
            f"(gefunden {item.tax_amount}).",
            f"items[{item.position}].tax_amount",
        ))
    return befunde
