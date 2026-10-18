"""Formatierung und Escaping fuer CII-Elemente."""
from decimal import Decimal, ROUND_HALF_UP

from app.services.einheiten import resolve_einheit


def fmt_date(d) -> str:
    return d.strftime("%Y%m%d")


def fmt_amount(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01"), ROUND_HALF_UP))


def unit_code(unit: str) -> str:
    """UN/ECE-Code aus dem zentralen Katalog. Unbekannt → UnknownUnitError, kein C62-Fallback."""
    return resolve_einheit(unit).un_code


def item_tax_category(rate: Decimal, invoice_tax_category: str) -> str:
    if invoice_tax_category != "S":
        return invoice_tax_category
    return "Z" if rate == Decimal("0") else "S"


def rate_percent_xml(rate: Decimal, tax_cat: str, indent: str) -> str:
    """BR-O-05: Kategorie O darf keinen Steuersatz (BT-152) tragen."""
    if tax_cat == "O":
        return ""
    return indent + f"<ram:RateApplicablePercent>{fmt_amount(rate)}</ram:RateApplicablePercent>"


def esc(text: str | None) -> str:
    if not text:
        return ""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
