"""IBAN/BIC normalisieren und pruefen (Firma und Kunde, EPC-QR)."""
from __future__ import annotations

from app.services.epc_qr import _normalize_bic
from app.services.iban import IbanProfil, pruefe_iban as _pruefe_iban_kern


def normalisiere_iban(roh: str | None) -> str | None:
    if not (roh or "").strip():
        return None
    return _pruefe_iban_kern(roh, IbanProfil.REGISTRY)


def normalisiere_bic(roh: str | None) -> str | None:
    if not (roh or "").strip():
        return None
    return _normalize_bic(roh)


def pruefe_iban(roh: str | None) -> str | None:
    """Fehlermeldung oder None (Formular-Fassade ueber die Kernregel)."""
    try:
        _pruefe_iban_kern(roh, IbanProfil.REGISTRY)
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


def iban_fuer_ausgabe(
    roh: str | None,
    *,
    wer: str,
    profil: IbanProfil = IbanProfil.REGISTRY,
) -> str | None:
    """Option A: ungueltige gespeicherte IBAN bricht mit sprechender Meldung ab."""
    try:
        return _pruefe_iban_kern(roh, profil)
    except ValueError as fehler:
        raise ValueError(
            f"Die IBAN von {wer} (Feld bank_iban) ist ungueltig: {fehler}"
        ) from fehler
