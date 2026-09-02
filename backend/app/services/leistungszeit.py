"""Leistungsdatum und Leistungszeitraum (§ 14 Abs. 4 Nr. 6 UStG, EN16931 BG-14)."""
from __future__ import annotations

from datetime import date

from app.models.invoice import Invoice


def hat_leistungszeitpunkt(invoice: Invoice) -> bool:
    """Einzeldatum oder vollständiger Zeitraum erfüllt die Pflichtangabe."""
    if invoice.delivery_date:
        return True
    return bool(invoice.service_period_start and invoice.service_period_end)


def leistungszeitraum_teilweise(invoice: Invoice) -> bool:
    start = invoice.service_period_start
    end = invoice.service_period_end
    return bool(start or end) and not (start and end)


def leistungszeitraum_ungueltig(invoice: Invoice) -> bool:
    start = invoice.service_period_start
    end = invoice.service_period_end
    if start and end:
        return start > end
    return False


def parse_optional_date(roh: str | None) -> date | None:
    s = (roh or "").strip()
    return date.fromisoformat(s) if s else None


def parse_leistungszeit_from_form(form) -> tuple[date | None, date | None, date | None]:
    return (
        parse_optional_date(form.get("delivery_date")),
        parse_optional_date(form.get("service_period_start")),
        parse_optional_date(form.get("service_period_end")),
    )
