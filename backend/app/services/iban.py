"""Einheitliche IBAN-Pruefung (ISO 13616 MOD 97-10, Registry-Laenge).

Oeffentliche Naht fuer Issue #91. Profile:
  REGISTRY: Zeichenvorrat, Registry-Laenge, MOD 97-10
  EPC_SCT:  REGISTRY plus Praefix im versionierten EPC-SCT-Satz

epc_qr und Formulare besitzen diese Regel nicht; sie rufen sie nur auf.
"""
from __future__ import annotations

from enum import Enum

from app.iban_daten import EPC_SCT_PRAEFIXE, IBAN_LAENGEN

_MAX_SCHUTZ = 34


class IbanProfil(str, Enum):
    REGISTRY = "REGISTRY"
    EPC_SCT = "EPC_SCT"


def pruefe_iban(roh: str | None, profil: IbanProfil = IbanProfil.REGISTRY) -> str | None:
    """Leer -> None. Gueltig -> normalisierte IBAN. Sonst ValueError."""
    if roh is None or not str(roh).split():
        return None
    norm = _normalisiere(roh)
    _syntax(norm)
    _laenge_und_praefix(norm)
    _mod97(norm)
    if profil is IbanProfil.EPC_SCT:
        _epc_satz(norm)
    return norm


def _normalisiere(roh: str) -> str:
    return "".join(roh.split()).upper()


def _syntax(norm: str) -> None:
    if len(norm) > _MAX_SCHUTZ:
        raise ValueError("IBAN ist zu lang.")
    if len(norm) < 5:
        raise ValueError("IBAN ist zu kurz.")
    if not norm.isalnum() or not all(ord(c) < 128 for c in norm):
        raise ValueError("IBAN enthaelt ungueltige Zeichen.")
    if not (norm[0].isalpha() and norm[1].isalpha()):
        raise ValueError("IBAN muss mit einem Laendercode beginnen.")
    if not (norm[2].isdigit() and norm[3].isdigit()):
        raise ValueError("IBAN-Pruefziffern muessen Ziffern sein.")


def _laenge_und_praefix(norm: str) -> None:
    praefix = norm[:2]
    erwartet = IBAN_LAENGEN.get(praefix)
    if erwartet is None:
        raise ValueError(f"IBAN-Laendercode {praefix} ist nicht registriert.")
    if len(norm) != erwartet:
        raise ValueError(
            f"IBAN-Laenge fuer {praefix} muss {erwartet} sein, nicht {len(norm)}."
        )


def _mod97(norm: str) -> None:
    umgestellt = norm[4:] + norm[:4]
    rest = 0
    for zeichen in umgestellt:
        if zeichen.isdigit():
            rest = (rest * 10 + int(zeichen)) % 97
        else:
            zahl = ord(zeichen) - 55  # A=10 ... Z=35
            rest = (rest * 10 + zahl // 10) % 97
            rest = (rest * 10 + zahl % 10) % 97
    if rest != 1:
        raise ValueError("IBAN-Pruefziffer ist ungueltig.")


def _epc_satz(norm: str) -> None:
    praefix = norm[:2]
    if praefix not in EPC_SCT_PRAEFIXE:
        raise ValueError(
            f"IBAN-Laendercode {praefix} gehoert nicht zum EPC-SCT-Satz."
        )
