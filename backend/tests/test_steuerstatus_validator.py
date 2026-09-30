"""Validator-Naht fuer Honorargutschrift-Steuerstatus (Faelle a-d)."""

from decimal import Decimal

from app.services.validator import validate_invoice
from tests.factories import (
    company_stub,
    customer_stub,
    item_stub,
    validator_invoice_stub,
)


def _codes(issues):
    return {i.code for i in issues}


def _kunde(**over):
    kw = dict(
        gutschriftempfaenger=True,
        ust_status="regelbesteuert",
        tax_number="12/345/67890",
        vat_id=None,
    )
    kw.update(over)
    return customer_stub(**kw)


def _hg(kunde=None, *, tax_category="S", tax_rate=Decimal("7.00"), items=None):
    netto = Decimal("100.00")
    steuer = (netto * tax_rate / 100).quantize(Decimal("0.01"))
    if items is None:
        items = [item_stub(
            quantity=Decimal("1"), unit_price=netto, tax_rate=tax_rate,
            net_amount=netto, tax_amount=steuer, gross_amount=netto + steuer,
        )]
    return validator_invoice_stub(
        invoice_type="self_billing",
        customer=kunde or _kunde(),
        tax_category=tax_category,
        net_total=netto,
        tax_total=steuer,
        gross_total=netto + steuer,
        items=items,
        original_invoice_id="dummy",
    )


def test_a_kein_gutschriftempfaenger_ist_fehler():
    inv = _hg(_kunde(gutschriftempfaenger=False))
    errors, _ = validate_invoice(inv, company_stub())
    assert "GUTSCHRIFTEMPFAENGER_ERFORDERLICH" in _codes(errors)
    assert any(e.field == "customer.gutschriftempfaenger" for e in errors
               if e.code == "GUTSCHRIFTEMPFAENGER_ERFORDERLICH")


def test_b_ungeklaerter_status_ist_fehler():
    inv = _hg(_kunde(ust_status="ungeklaert"))
    errors, _ = validate_invoice(inv, company_stub())
    assert "UST_STATUS_UNGEKLAERT" in _codes(errors)
    assert any(e.field == "customer.ust_status" for e in errors
               if e.code == "UST_STATUS_UNGEKLAERT")


def test_c_nur_steuernummer_reicht():
    inv = _hg(_kunde(tax_number="12/345/67890", vat_id=None))
    errors, _ = validate_invoice(inv, company_stub())
    assert "CUSTOMER_TAX_ID_MISSING" not in _codes(errors)


def test_c_nur_ust_id_reicht():
    inv = _hg(_kunde(tax_number=None, vat_id="DE123456789"))
    errors, _ = validate_invoice(inv, company_stub())
    assert "CUSTOMER_TAX_ID_MISSING" not in _codes(errors)


def test_c_beide_kennungen_reichen():
    inv = _hg(_kunde(tax_number="12/345/67890", vat_id="DE123456789"))
    errors, _ = validate_invoice(inv, company_stub())
    assert "CUSTOMER_TAX_ID_MISSING" not in _codes(errors)


def test_c_weder_steuernummer_noch_ust_id_ist_fehler():
    inv = _hg(_kunde(tax_number=None, vat_id=None))
    errors, _ = validate_invoice(inv, company_stub())
    assert "CUSTOMER_TAX_ID_MISSING" in _codes(errors)
    assert any(e.field == "customer.tax" for e in errors
               if e.code == "CUSTOMER_TAX_ID_MISSING")


def test_d_regelbesteuert_mit_e_und_null_ist_fehler():
    inv = _hg(
        _kunde(ust_status="regelbesteuert"),
        tax_category="E",
        tax_rate=Decimal("0.00"),
    )
    errors, _ = validate_invoice(inv, company_stub())
    assert "UST_STATUS_STEUER_MISMATCH" in _codes(errors)


def test_d_kleinunternehmer_mit_s_und_sieben_ist_fehler():
    inv = _hg(
        _kunde(ust_status="kleinunternehmer"),
        tax_category="S",
        tax_rate=Decimal("7.00"),
    )
    errors, _ = validate_invoice(inv, company_stub())
    assert "UST_STATUS_STEUER_MISMATCH" in _codes(errors)


def test_d_nur_eine_position_weicht_ab():
    """Kopf stimmt (S/7), zweite Position traegt 0: Positionspruefung greift."""
    gute = item_stub(
        position=1, quantity=Decimal("1"), unit_price=Decimal("50.00"),
        tax_rate=Decimal("7.00"), net_amount=Decimal("50.00"),
        tax_amount=Decimal("3.50"), gross_amount=Decimal("53.50"),
    )
    schlechte = item_stub(
        position=2, quantity=Decimal("1"), unit_price=Decimal("50.00"),
        tax_rate=Decimal("0.00"), net_amount=Decimal("50.00"),
        tax_amount=Decimal("0.00"), gross_amount=Decimal("50.00"),
    )
    inv = validator_invoice_stub(
        invoice_type="self_billing",
        customer=_kunde(ust_status="regelbesteuert"),
        tax_category="S",
        net_total=Decimal("100.00"),
        tax_total=Decimal("7.00"),
        gross_total=Decimal("107.00"),
        items=[gute, schlechte],
        original_invoice_id="dummy",
    )
    errors, _ = validate_invoice(inv, company_stub())
    mismatch = [e for e in errors if e.code == "UST_STATUS_STEUER_MISMATCH"]
    assert mismatch
    assert any(e.field and "items[2]" in e.field for e in mismatch)


def test_regelbesteuert_mit_s_und_sieben_ist_ok():
    inv = _hg(_kunde(ust_status="regelbesteuert"))
    errors, _ = validate_invoice(inv, company_stub())
    assert "UST_STATUS_STEUER_MISMATCH" not in _codes(errors)
    assert "UST_STATUS_UNGEKLAERT" not in _codes(errors)
    assert "GUTSCHRIFTEMPFAENGER_ERFORDERLICH" not in _codes(errors)


def test_kleinunternehmer_mit_e_und_null_ist_ok():
    inv = _hg(
        _kunde(ust_status="kleinunternehmer"),
        tax_category="E",
        tax_rate=Decimal("0.00"),
    )
    errors, _ = validate_invoice(inv, company_stub())
    assert "UST_STATUS_STEUER_MISMATCH" not in _codes(errors)
