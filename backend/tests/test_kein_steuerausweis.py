"""Kein Steuerausweis bei AE, K, O und E (#182).

Bei diesen Kategorien darf weder Positions- noch Kopf-Steuerbetrag von null
abweichen. Die 0,02-€-Toleranz der allgemeinen Betragspruefung gilt hier nicht:
unberechtigt ausgewiesene Steuer wird nach § 14c UStG geschuldet.
"""
from decimal import Decimal

import pytest

from app.services.validator import validate_invoice
from tests.factories import (
    orm_company as _company,
    orm_invoice as _invoice,
    orm_item as _item,
)


def _codes(inv):
    errors, _ = validate_invoice(inv, _company())
    return {e.code for e in errors}


@pytest.mark.parametrize("kategorie", ["O", "E"])
def test_steuerkategorie_positions_steuer_ein_cent_abgelehnt(kategorie):
    item = _item(1, "1", "100.00", "0")
    item.tax_amount = Decimal("0.01")
    item.gross_amount = item.net_amount + item.tax_amount
    inv = _invoice(
        [item],
        tax_category=kategorie,
        tax=Decimal("0.01"),
        gross=item.gross_amount,
    )
    assert "TAX_AMOUNT_MUST_BE_ZERO" in _codes(inv)


@pytest.mark.parametrize("kategorie", ["O", "E"])
def test_steuerkategorie_kopf_tax_total_ein_cent_abgelehnt(kategorie):
    item = _item(1, "1", "100.00", "0")
    inv = _invoice([item], tax_category=kategorie)
    inv.tax_total = Decimal("0.01")
    inv.gross_total = inv.net_total + inv.tax_total
    assert "TAX_AMOUNT_MUST_BE_ZERO" in _codes(inv)


@pytest.mark.parametrize("kategorie", ["AE", "K"])
def test_ae_und_k_bleiben_bei_steuerbetrag_abweichung_abgelehnt(kategorie):
    """Gegentest: bestehende AE/K-Regel bleibt wirksam."""
    from datetime import date

    item = _item(1, "1", "100.00", "0")
    item.tax_amount = Decimal("0.01")
    item.gross_amount = item.net_amount + item.tax_amount
    kwargs = dict(tax_category=kategorie, tax=Decimal("0.01"), gross=item.gross_amount)
    if kategorie == "K":
        kwargs["delivery_date"] = date(2026, 6, 1)
    inv = _invoice([item], **kwargs)
    assert "TAX_AMOUNT_MUST_BE_ZERO" in _codes(inv)


def test_kategorie_s_toleranz_ein_cent_bleibt_erlaubt():
    """Gegentest: bei S bleibt 0,01 innerhalb der 0,02-€-Toleranz zulaessig."""
    item = _item(1, "1", "100.00", "19")
    expected = (item.net_amount * Decimal("19") / 100).quantize(Decimal("0.01"))
    item.tax_amount = expected + Decimal("0.01")
    item.gross_amount = item.net_amount + item.tax_amount
    inv = _invoice(
        [item],
        tax_category="S",
        tax=item.tax_amount,
        gross=item.gross_amount,
    )
    codes = _codes(inv)
    assert "ITEM_TAX_MISMATCH" not in codes
    assert "TAX_AMOUNT_MUST_BE_ZERO" not in codes
