"""Belegliste aufbereiten: Wartezustand und Kettenreihenfolge (#233).

Der Leser-Befund bleibt unveraendert (KETTE_SPRINGT). Nur die Anzeige in der
Liste wird neutral, wenn der genannte Vorgaenger im selben Ordner liegt und
noch in der Warteschlange zur Annahme steht (angenommen oder selbst wartend,
noch nicht angelegt).
"""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.services.uebergabe_befund import Belegurteil, Feststellung, beleg_beurteilen
from app.services.uebergabe_eingang import DatenbankLage
from app.services.uebergabe_listenzeile import zeile_aus_urteil

logger = logging.getLogger(__name__)


def zeile_aus_datei(
    datei: Path,
    db: Session,
    *,
    schluessel_wurzel: Optional[Path],
    anlagen_ordner: Optional[Path],
) -> dict:
    """Ein Beleg, ein Befund. Der Befund entsteht hier und nicht in der Ansicht."""
    roh = datei.read_bytes()
    try:
        urteil = beleg_beurteilen(
            roh,
            # Nur mit Anlagenordner sieht der Leser des § 8b die Dateien -
            # ohne ihn ist ANLAGE_FEHLT die ehrliche Antwort der Lage.
            DatenbankLage(db, anlagen_ordner=anlagen_ordner),
            schluessel_wurzel=schluessel_wurzel,
        )
    except Exception:
        # Sicherheitsnetz, kein Ersatz fuer die Befunde des Lesers: Eine
        # Kaputtheit, die dieser noch nicht kennt, darf nur EINE Zeile der
        # Liste kosten und nicht die ganze Seite (HTTP 500). Der Befund ist
        # BELEG_UNLESBAR, weil hier niemand sagen kann, was mit den Bytes
        # los ist; das Wesentliche steht in der Logzeile mit dem Traceback.
        logger.exception("Beurteilung von %s gescheitert", datei.name)
        urteil = Belegurteil(
            beleg_sha256=hashlib.sha256(roh).hexdigest(),
            feststellungen=(Feststellung("BELEG_UNLESBAR", "$"),),
        )
    return zeile_aus_urteil(datei.name, urteil)


def zeilen_aus_ordner(
    ordner: Path,
    db: Session,
    *,
    schluessel_wurzel: Optional[Path],
    anlagen_ordner_fuer: Callable[[Path], Optional[Path]],
) -> list[dict]:
    """Alle JSON-Belege beurteilen, Wartezustand setzen, Kettenreihenfolge."""
    zeilen = [
        zeile_aus_datei(
            datei,
            db,
            schluessel_wurzel=schluessel_wurzel,
            anlagen_ordner=anlagen_ordner_fuer(datei.parent),
        )
        for datei in sorted(ordner.glob("*.json"))
    ]
    return listen_aufbereiten(zeilen)


def _nach_sha(zeilen: list[dict]) -> dict:
    return {z["urteil"].beleg_sha256: z for z in zeilen}


def _ist_offen_in_kette(zeile: dict, nach_sha: dict, gesehen: set) -> bool:
    """Vorgaenger ist annehmbar-offen oder wartet selbst auf einen offenen."""
    urteil = zeile["urteil"]
    if urteil.bereits_verarbeitet:
        return False
    if urteil.angenommen:
        return True
    if urteil.befund != "KETTE_SPRINGT":
        return False
    vh = urteil.vorgaenger_hash
    if not vh or vh not in nach_sha or vh in gesehen:
        return False
    return _ist_offen_in_kette(nach_sha[vh], nach_sha, gesehen | {vh})


def warte_auf_dateiname(zeile: dict, nach_sha: dict) -> str | None:
    """Dateiname des Vorgaengers, wenn die Liste „wartet“ zeigen soll."""
    urteil = zeile["urteil"]
    if urteil.befund != "KETTE_SPRINGT":
        return None
    vh = urteil.vorgaenger_hash
    if not vh:
        return None
    vorgaenger = nach_sha.get(vh)
    if vorgaenger is None:
        return None
    if not _ist_offen_in_kette(vorgaenger, nach_sha, set()):
        return None
    return vorgaenger["dateiname"]


def annotiere_wartezustand(zeilen: list[dict]) -> None:
    """Setzt befund_anzeige / befund_neutral fuer wartende Folgebelege."""
    nach_sha = _nach_sha(zeilen)
    for zeile in zeilen:
        name = warte_auf_dateiname(zeile, nach_sha)
        if name is None:
            continue
        zeile["befund_anzeige"] = f"wartet auf Vorgänger {name}"
        zeile["befund_neutral"] = True


def kettenreihenfolge(zeilen: list[dict]) -> list[dict]:
    """Kettenreihenfolge aus vorgaenger_hash; sonst nach Dateiname."""
    nach_sha = _nach_sha(zeilen)
    kinder: dict[str, list] = defaultdict(list)
    wurzeln = []
    for zeile in zeilen:
        vh = zeile["urteil"].vorgaenger_hash
        if vh and vh in nach_sha:
            kinder[vh].append(zeile)
        else:
            wurzeln.append(zeile)

    def kette_ab(zeile: dict, gesehen: set) -> list[dict]:
        sha = zeile["urteil"].beleg_sha256
        if sha in gesehen:
            return []
        gesehen.add(sha)
        folge = [zeile]
        for kind in sorted(kinder[sha], key=lambda z: z["dateiname"]):
            folge.extend(kette_ab(kind, gesehen))
        return folge

    gesehen: set = set()
    ergebnis: list[dict] = []
    for wurzel in sorted(wurzeln, key=lambda z: z["dateiname"]):
        ergebnis.extend(kette_ab(wurzel, gesehen))
    for zeile in sorted(zeilen, key=lambda z: z["dateiname"]):
        if zeile["urteil"].beleg_sha256 not in gesehen:
            ergebnis.extend(kette_ab(zeile, gesehen))
    return ergebnis


def listen_aufbereiten(zeilen: list[dict]) -> list[dict]:
    """Wartezustand setzen und nach Kettenreihenfolge ordnen."""
    annotiere_wartezustand(zeilen)
    return kettenreihenfolge(zeilen)
