"""EPC-QR (Girocode) für SEPA-Überweisungen (#52)."""
from decimal import Decimal

import pytest

from app.services.epc_qr import build_epc_payload, qr_png_bytes


def test_epc_payload_mit_iban_betrag_und_verwendungszweck():
    payload = build_epc_payload(
        beneficiary_name="Muster Handwerk GmbH",
        iban="DE00 1234 5678 0000 0000 00",
        bic="ABCDDEFF",
        amount=Decimal("238.00"),
        remittance="RE-2026-777",
    )
    lines = payload.split("\n")
    assert lines == [
        "BCD",
        "002",
        "1",
        "SCT",
        "ABCDDEFF",
        "Muster Handwerk GmbH",
        "DE00123456780000000000",
        "EUR238.00",
        "",
        "",
        "RE-2026-777",
        "",
    ]


def test_epc_payload_ohne_bic():
    payload = build_epc_payload(
        beneficiary_name="Firma",
        iban="DE00123456780000000000",
        amount=Decimal("1.50"),
        remittance="RE-1",
    )
    assert payload.split("\n")[4] == ""


def test_epc_payload_kuerzt_langen_namen():
    name = "A" * 90
    payload = build_epc_payload(
        beneficiary_name=name,
        iban="DE00123456780000000000",
        amount=Decimal("10.00"),
    )
    assert payload.split("\n")[5] == "A" * 70


def test_epc_payload_lehnt_ungueltige_iban_ab():
    with pytest.raises(ValueError, match="IBAN"):
        build_epc_payload(
            beneficiary_name="Firma",
            iban="",
            amount=Decimal("10.00"),
        )


def test_qr_png_bytes_erzeugt_png():
    payload = build_epc_payload(
        beneficiary_name="Firma",
        iban="DE00123456780000000000",
        amount=Decimal("10.00"),
        remittance="RE-1",
    )
    png = qr_png_bytes(payload)
    assert png.startswith(b"\x89PNG")
