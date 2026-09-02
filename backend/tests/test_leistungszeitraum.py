"""Leistungszeitraum von/bis auf Rechnungen und Gutschriften."""

from datetime import date
from decimal import Decimal

import pytest

from app.services.leistungszeit import hat_leistungszeitpunkt
from app.services.validator import validate_invoice
from app.services.zugferd_xml import generate_xml
from tests.factories import (
    company_stub,
    customer_stub,
    item_stub,
    validator_invoice_stub,
    zugferd_invoice_stub,
)

NS = {
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
}


def _invoice(**kw):
    return validator_invoice_stub(**kw)


def test_zeitraum_allein_erfuellt_pflichtangabe():
    inv = _invoice(
        delivery_date=None,
        service_period_start=date(2026, 7, 1),
        service_period_end=date(2026, 9, 30),
        gross_total=Decimal("500.00"),
    )
    errors, _ = validate_invoice(inv, company_stub())
    assert not any(e.code == "DELIVERY_DATE_MISSING" for e in errors)


def test_nur_von_ist_fehler():
    inv = _invoice(
        delivery_date=None,
        service_period_start=date(2026, 7, 1),
        service_period_end=None,
        gross_total=Decimal("500.00"),
    )
    errors, _ = validate_invoice(inv, company_stub())
    assert any(e.code == "SERVICE_PERIOD_INCOMPLETE" for e in errors)


def test_von_nach_bis_ist_fehler():
    inv = _invoice(
        delivery_date=None,
        service_period_start=date(2026, 9, 30),
        service_period_end=date(2026, 7, 1),
        gross_total=Decimal("500.00"),
    )
    errors, _ = validate_invoice(inv, company_stub())
    assert any(e.code == "SERVICE_PERIOD_INVALID" for e in errors)


def test_hat_leistungszeitpunkt():
    assert hat_leistungszeitpunkt(_invoice(delivery_date=date(2026, 1, 1)))
    assert hat_leistungszeitpunkt(_invoice(
        delivery_date=None,
        service_period_start=date(2026, 7, 1),
        service_period_end=date(2026, 9, 30),
    ))
    assert not hat_leistungszeitpunkt(_invoice(delivery_date=None))


def test_xml_enthaelt_billing_specified_period():
    inv = zugferd_invoice_stub(
        delivery_date=None,
        service_period_start=date(2026, 7, 1),
        service_period_end=date(2026, 9, 30),
    )
    xml = generate_xml(inv, company_stub())
    assert "BillingSpecifiedPeriod" in xml
    assert "20260701" in xml
    assert "20260930" in xml


def test_ig_lieferung_mit_zeitraum_ohne_einzeldatum():
    inv = _invoice(
        delivery_date=None,
        service_period_start=date(2026, 6, 1),
        service_period_end=date(2026, 6, 30),
        tax_category="K",
        gross_total=Decimal("100.00"),
        customer=customer_stub(country="AT", vat_id="ATU12345678"),
    )
    errors, _ = validate_invoice(inv, company_stub())
    assert not any(e.code == "DELIVERY_DATE_MISSING" for e in errors)
