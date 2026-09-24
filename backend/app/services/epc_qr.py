"""EPC-QR (Girocode) nach EPC069-12 / SEPA Credit Transfer (#52).

Banking-Apps lesen den QR als SEPA-Überweisungsauftrag. Der Payload ist ein
zeilenbasiertes Textformat (Version 002), kein proprietäres Schema.
"""
from __future__ import annotations

import io
import re
from decimal import Decimal

import qrcode

from app.services.iban import IbanProfil, pruefe_iban

_BIC_RE = re.compile(r"^[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def _normalize_bic(bic: str | None) -> str:
    if not bic:
        return ""
    cleaned = "".join(bic.split()).upper()
    if not _BIC_RE.match(cleaned):
        raise ValueError("BIC ist ungueltig.")
    return cleaned


def build_epc_payload(
    *,
    beneficiary_name: str,
    iban: str,
    amount: Decimal,
    currency: str = "EUR",
    bic: str | None = None,
    remittance: str | None = None,
) -> str:
    """Erzeugt den EPC-Payload (Version 002) fuer einen SCT-QR."""
    name = (beneficiary_name or "").strip()[:70]
    if not name:
        raise ValueError("Name des Zahlungsempfaengers fehlt.")
    iban_norm = pruefe_iban(iban, IbanProfil.EPC_SCT)
    if iban_norm is None:
        raise ValueError("IBAN fehlt oder ist ungueltig.")
    bic_norm = _normalize_bic(bic)
    cur = (currency or "EUR").upper()
    if cur != "EUR":
        raise ValueError("EPC-QR unterstuetzt nur EUR.")
    if amount <= 0:
        raise ValueError("Betrag muss positiv sein.")
    amount_str = f"{cur}{amount.quantize(Decimal('0.01'))}"
    info = (remittance or "").strip()[:140]
    lines = [
        "BCD",
        "002",
        "1",
        "SCT",
        bic_norm,
        name,
        iban_norm,
        amount_str,
        "",
        "",
        info,
        "",
    ]
    return "\n".join(lines)


def qr_png_bytes(payload: str, *, box_size: int = 4, border: int = 2) -> bytes:
    """Rendert den Payload als PNG fuer die PDF-Einbettung."""
    qr = qrcode.QRCode(box_size=box_size, border=border)
    qr.add_data(payload)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image().save(buf, format="PNG")
    return buf.getvalue()
