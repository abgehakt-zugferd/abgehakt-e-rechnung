"""Öffentliche Schlüssel der Übergabe-Absender (§ 6 UEBERGABEFORMAT).

Parallele zu tantiemen-app/storage/schluessel.py — eigene Kopie, damit die
Signaturprüfung hier nicht die des Absenders importiert.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.serialization import load_pem_public_key

_WURZEL = Path(__file__).resolve().parents[2] / "schluessel"


class SchluesselUnbekannt(LookupError):
    """Signiert mit etwas, das hier niemand hinterlegt hat."""


class SchluesselNichtGueltig(ValueError):
    """Der Schlüssel gibt es, er galt zu diesem Zeitpunkt aber nicht."""


def _zeit(wert: Optional[str]) -> Optional[datetime]:
    if wert is None:
        return None
    return datetime.fromisoformat(wert.replace("Z", "+00:00"))


def schluessel_laden(
    absender: str,
    schluessel_id: str,
    erzeugt_am: datetime,
    wurzel: Optional[Path] = None,
):
    """Öffentlicher Schlüssel für den Erzeugungszeitpunkt des Belegs."""
    ordner = Path(wurzel) if wurzel else _WURZEL
    pem = ordner / absender / f"{schluessel_id}.pub"
    beiblatt = ordner / absender / f"{schluessel_id}.json"
    if not pem.exists() or not beiblatt.exists():
        raise SchluesselUnbekannt(f"{absender}/{schluessel_id}")

    angaben = json.loads(beiblatt.read_text(encoding="utf-8"))
    von = _zeit(angaben.get("gueltig_von"))
    bis = _zeit(angaben.get("gueltig_bis"))
    if von is None or erzeugt_am < von:
        raise SchluesselNichtGueltig(
            f"{absender}/{schluessel_id} galt am {erzeugt_am.isoformat()} noch nicht"
        )
    if bis is not None and erzeugt_am >= bis:
        raise SchluesselNichtGueltig(
            f"{absender}/{schluessel_id} galt am {erzeugt_am.isoformat()} nicht mehr"
        )
    return load_pem_public_key(pem.read_bytes())
