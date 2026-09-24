"""
Parametrisierte Betrags-/Steuersatz-Prüfung des Validators (Audit-#9).

Bisher gab es KEIN @pytest.mark.parametrize — Steuersatz-Kombinationen, gemischte
Sätze, Rundungs- und Toleranzgrenzen (0,02 €) waren nur als Einzelfälle abgedeckt.
Hier systematisch: konsistente Summen erzeugen KEINE Mismatch-Fehler, jenseits der
Toleranz DOCH; ungültige Sätze werden erkannt.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.services.validator import validate_invoice
from tests.factories import (
    orm_company as _company,
    orm_customer as _customer,
    orm_invoice as _invoice,
    orm_item as _item,
)

_MISMATCH = {"NET_TOTAL_MISMATCH", "TAX_TOTAL_MISMATCH", "GROSS_TOTAL_MISMATCH",
             "ITEM_AMOUNT_MISMATCH", "ITEM_TAX_MISMATCH"}


def _codes(inv):
    errors, _ = validate_invoice(inv, _company())
    return {e.code for e in errors}


# ── Konsistente Summen über Steuersätze/Kombinationen → keine Mismatch-Fehler ──

@pytest.mark.parametrize("rate", ["19", "7", "0"])
def test_single_rate_consistent_has_no_mismatch(rate):
    inv = _invoice([_item(1, "2", "100.00", rate)])
    assert _MISMATCH.isdisjoint(_codes(inv))


def test_mixed_rates_sum_correctly():
    items = [_item(1, "2", "100.00", "19"), _item(2, "1", "50.00", "7")]
    # net 200+50=250, tax 38+3.50=41.50, gross 291.50
    inv = _invoice(items)
    assert _MISMATCH.isdisjoint(_codes(inv))


@pytest.mark.parametrize("qty,price,rate", [
    ("1", "0.01", "19"),      # Kleinstbetrag: net 0.01, tax 0.00
    ("3", "33.33", "19"),     # net 99.99
    ("7", "14.29", "7"),      # krumme Rundung
])
def test_rounding_edge_cases_consistent(qty, price, rate):
    inv = _invoice([_item(1, qty, price, rate)])
    assert _MISMATCH.isdisjoint(_codes(inv))


# ── Toleranzgrenze 0,02 € ────────────────────────────────────────────────────

def test_total_within_tolerance_ok():
    inv = _invoice([_item(1, "2", "100.00", "19")])
    inv.gross_total = inv.gross_total + Decimal("0.02")   # exakt an der Grenze
    assert "GROSS_TOTAL_MISMATCH" not in _codes(inv)


def test_total_beyond_tolerance_flagged():
    inv = _invoice([_item(1, "2", "100.00", "19")])
    inv.gross_total = inv.gross_total + Decimal("0.03")   # jenseits der Toleranz
    assert "GROSS_TOTAL_MISMATCH" in _codes(inv)


def test_item_net_within_tolerance_ok():
    """#33: Positions-Toleranz an der 0,02-€-Grenze, nicht nur gross_total."""
    item = _item(1, "2", "100.00", "19")
    item.net_amount = item.net_amount + Decimal("0.02")
    item.tax_amount = (item.net_amount * Decimal("19") / 100).quantize(Decimal("0.01"))
    item.gross_amount = item.net_amount + item.tax_amount
    inv = _invoice([item])
    assert "ITEM_AMOUNT_MISMATCH" not in _codes(inv)


def test_item_net_beyond_tolerance_flagged():
    item = _item(1, "2", "100.00", "19")
    item.net_amount = item.net_amount + Decimal("0.03")
    item.tax_amount = (item.net_amount * Decimal("19") / 100).quantize(Decimal("0.01"))
    item.gross_amount = item.net_amount + item.tax_amount
    inv = _invoice([item])
    assert "ITEM_AMOUNT_MISMATCH" in _codes(inv)


# ── Ungültige Steuersätze ────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_rate", ["10", "16", "20"])
def test_invalid_tax_rate_flagged(bad_rate):
    inv = _invoice([_item(1, "1", "100.00", bad_rate)])
    assert "TAX_RATE_INVALID" in _codes(inv)


# ── Reverse-Charge (AE) verlangt 0 % ─────────────────────────────────────────

def test_reverse_charge_with_nonzero_rate_flagged():
    inv = _invoice([_item(1, "1", "100.00", "19")], tax_category="AE")
    assert "TAX_CATEGORY_RATE_MISMATCH" in _codes(inv)


def test_reverse_charge_zero_rate_ok():
    inv = _invoice([_item(1, "1", "100.00", "0")], tax_category="AE")
    assert "TAX_CATEGORY_RATE_MISMATCH" not in _codes(inv)


def test_ae_zwei_cent_steuerbetrag_wird_abgelehnt():
    """Bei AE greift keine 0,02-€-Toleranz: Steuerbetrag muss exakt null sein."""
    item = _item(1, "1", "100.00", "0")
    item.tax_amount = Decimal("0.02")
    item.gross_amount = item.net_amount + item.tax_amount
    inv = _invoice([item], tax_category="AE",
                   tax=Decimal("0.02"), gross=item.gross_amount)
    codes = _codes(inv)
    assert "TAX_AMOUNT_MUST_BE_ZERO" in codes
    assert "ITEM_TAX_MISMATCH" not in codes  # globale Toleranz wuerde 0,02 durchlassen


def test_ae_exakt_null_steuerbetrag_ist_zulaessig():
    inv = _invoice([_item(1, "1", "100.00", "0")], tax_category="AE")
    assert "TAX_AMOUNT_MUST_BE_ZERO" not in _codes(inv)


def test_k_zwei_cent_steuerbetrag_wird_abgelehnt():
    item = _item(1, "1", "100.00", "0")
    item.tax_amount = Decimal("0.02")
    item.gross_amount = item.net_amount + item.tax_amount
    inv = _invoice([item], tax_category="K",
                   tax=Decimal("0.02"), gross=item.gross_amount,
                   delivery_date=date(2026, 6, 1))
    assert "TAX_AMOUNT_MUST_BE_ZERO" in _codes(inv)


def test_ae_steuersumme_zwei_cent_wird_abgelehnt():
    """Position exakt null, Summe um zwei Cent verdorben: eigene Regel greift."""
    item = _item(1, "1", "100.00", "0")
    inv = _invoice([item], tax_category="AE")
    inv.tax_total = Decimal("0.02")
    inv.gross_total = inv.net_total + inv.tax_total
    codes = _codes(inv)
    assert "TAX_AMOUNT_MUST_BE_ZERO" in codes
    assert "TAX_TOTAL_MISMATCH" not in codes  # 0,02 waere innerhalb der Toleranz
