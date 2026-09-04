"""Öffentliche Schlüssel der Übergabe-Absender (§ 6 UEBERGABEFORMAT).

Parallele zu tantiemen-app/storage/schluessel.py — eigene Kopie, damit die
Signaturprüfung hier nicht die des Absenders importiert.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.serialization import load_pem_public_key

from app.installation import is_testinstanz

_WURZEL = Path(__file__).resolve().parents[2] / "schluessel"

# Ein Probeschluessel ist am NAMEN erkennbar und gilt nur in einer Testinstanz.
# Am Namen und nicht an einer Angabe im Beiblatt: das Beiblatt liegt beim
# Empfaenger und kann verrutschen, der Name steht in jedem signierten Beleg.
PROBE_KENNZEICHEN = "-probe-"


class SchluesselUnbekannt(LookupError):
    """Signiert mit etwas, das hier niemand hinterlegt hat."""


class SchluesselNichtGueltig(ValueError):
    """Der Schlüssel gibt es, er galt zu diesem Zeitpunkt aber nicht."""


class ProbeschluesselImEchtlauf(SchluesselUnbekannt):
    """Ein Probeschlüssel, und diese Installation ist keine Testinstanz.

    Eine Kettenprobe darf nie den echten Bestand berühren, und ein
    Probeschlüssel, der im Echtlauf gälte, hebt genau diese Trennung auf.
    """


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
    if PROBE_KENNZEICHEN in schluessel_id and not is_testinstanz():
        raise ProbeschluesselImEchtlauf(
            f"{schluessel_id} ist ein Probeschlüssel und gilt nur in der Testinstanz"
        )

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
