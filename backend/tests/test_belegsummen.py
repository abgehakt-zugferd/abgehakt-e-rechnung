"""Tests fuer belegsummen: Belegsummen mit und ohne Abzug (EN 16931 BG-20)."""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.belegsummen import belegsummen


def _position(netto, steuer, satz):
    return SimpleNamespace(
        net_amount=Decimal(netto),
        tax_amount=Decimal(steuer),
        tax_rate=Decimal(satz),
    )


def test_ohne_abzug_summiert_positionssteuern_statt_neu_zu_rechnen():
    # Jede Position einzeln gerundet: 6.34 * 19 % = 1.2046 -> 1.20, Summe 2.40.
    # Auf der Summe gerecht waere 12.68 * 19 % = 2.4092 -> 2.41, ein Cent mehr.
    positionen = [
        _position("6.34", "1.20", "19"),
        _position("6.34", "1.20", "19"),
    ]
    summen = belegsummen(positionen, None)
    assert summen.positionen_netto == Decimal("12.68")
    assert summen.abzug == Decimal("0.00")
    assert summen.steuerbasis == Decimal("12.68")
    assert summen.steuer == Decimal("2.40")
    assert summen.brutto == Decimal("15.08")


def test_abzug_bei_19_prozent():
    positionen = [_position("1000.00", "190.00", "19")]
    summen = belegsummen(positionen, Decimal("100.00"))
    assert summen.positionen_netto == Decimal("1000.00")
    assert summen.abzug == Decimal("100.00")
    assert summen.steuerbasis == Decimal("900.00")
    assert summen.steuer == Decimal("171.00")
    assert summen.brutto == Decimal("1071.00")


def test_abzug_bei_null_prozent():
    positionen = [_position("5000.00", "0.00", "0")]
    summen = belegsummen(positionen, Decimal("3500.00"))
    assert summen.positionen_netto == Decimal("5000.00")
    assert summen.steuerbasis == Decimal("1500.00")
    assert summen.steuer == Decimal("0.00")
    assert summen.brutto == Decimal("1500.00")


def test_abzug_mit_mehreren_steuersaetzen_abgelehnt():
    positionen = [
        _position("100.00", "19.00", "19"),
        _position("50.00", "0.00", "0"),
    ]
    with pytest.raises(ValueError):
        belegsummen(positionen, Decimal("10.00"))


def test_abzug_nur_positive_werte_erlaubt():
    positionen = [_position("100.00", "19.00", "19")]
    with pytest.raises(ValueError):
        belegsummen(positionen, Decimal("0.00"))
    with pytest.raises(ValueError):
        belegsummen(positionen, Decimal("-1.00"))


def test_abzug_kleiner_als_positionen_netto_erforderlich():
    positionen = [_position("100.00", "19.00", "19")]
    with pytest.raises(ValueError):
        belegsummen(positionen, Decimal("100.00"))
    with pytest.raises(ValueError):
        belegsummen(positionen, Decimal("150.00"))


def test_abzug_ohne_positionen_abgelehnt():
    with pytest.raises(ValueError):
        belegsummen([], Decimal("10.00"))
