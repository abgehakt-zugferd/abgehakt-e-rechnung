"""IBAN/BIC normalisieren und pruefen (Firma und Kunde, EPC-QR)."""
from __future__ import annotations

from app.services.epc_qr import _normalize_bic, _normalize_iban


def normalisiere_iban(roh: str | None) -> str | None:
    if not (roh or "").strip():
        return None
    return _normalize_iban(roh)


def normalisiere_bic(roh: str | None) -> str | None:
    if not (roh or "").strip():
        return None
    return _normalize_bic(roh)


def pruefe_iban(roh: str | None) -> str | None:
    """Fehlermeldung oder None."""
    if not (roh or "").strip():
        return None
    try:
        _normalize_iban(roh)
    except ValueError as fehler:
        return str(fehler)
    return None


def pruefe_bic(roh: str | None) -> str | None:
    if not (roh or "").strip():
        return None
    try:
        _normalize_bic(roh)
    except ValueError as fehler:
        return str(fehler)
    return None
