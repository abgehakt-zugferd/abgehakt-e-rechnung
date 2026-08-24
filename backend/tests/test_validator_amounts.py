"""
Parametrisierte Betrags-/Steuersatz-Prüfung des Validators (Audit-#9).

Bisher gab es KEIN @pytest.mark.parametrize — Steuersatz-Kombinationen, gemischte
Sätze, Rundungs- und Toleranzgrenzen (0,02 €) waren nur als Einzelfälle abgedeckt.
Hier systematisch: konsistente Summen erzeugen KEINE Mismatch-Fehler, jenseits der
Toleranz DOCH; ungültige Sätze werden erkannt.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.validator import validate_invoice

_MISMATCH = {"NET_TOTAL_MISMATCH", "TAX_TOTAL_MISMATCH", "GROSS_TOTAL_MISMATCH",
             "ITEM_AMOUNT_MISMATCH", "ITEM_TAX_MISMATCH"}


def _company():
    return Company(id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
                   zip_code="12345", city="Musterstadt", country="DE",
                   tax_number="123/456/78901", vat_id="DE123456789")


def _customer():
    return Customer(name="Kunde GmbH", address_line1="Weg 1", zip_code="10115",
                    city="Berlin", country="DE", vat_id="DE987654321")


def _item(pos, qty, price, rate):
    net = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"), ROUND_HALF_UP)
    tax = (net * Decimal(rate) / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return InvoiceItem(position=pos, description="Leistung", unit="Stk",
                       quantity=Decimal(qty), unit_price=Decimal(price),
                       tax_rate=Decimal(rate), net_amount=net, tax_amount=tax,
                       gross_amount=net + tax)


def _invoice(items, *, net=None, tax=None, gross=None, tax_category="S"):
    net = net if net is not None else sum(i.net_amount for i in items)
    tax = tax if tax is not None else sum(i.tax_amount for i in items)
    gross = gross if gross is not None else net + tax
    inv = Invoice(invoice_number="RE-2026-001", issue_date=date(2026, 6, 1),
                  due_date=date(2026, 6, 15), currency="EUR", net_total=net,
                  tax_total=tax, gross_total=gross, tax_category=tax_category,
                  payment_terms="14 Tage")
    inv.customer = _customer()
    inv.items = items
    return inv


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
