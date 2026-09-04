#!/usr/bin/env python3
"""CLI: Belege im Uebergabeordner beurteilen und den Befund ausgeben.

LIEST NUR. Das Skript legt nichts an und merkt sich nichts: Entwuerfe entstehen
ausschliesslich ueber den Knopf in der Oberflaeche (abgehakt#22, Punkt 4). Es
ist damit das, was man vor dem ersten Knopfdruck laufen laesst - und was in der
Testinstanz zeigt, ob die Kette ueberhaupt ankommt.

Umgebung: UEBERGABEN_ORDNER (Pflicht), SCHLUESSEL_PFAD (sonst backend/schluessel).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from app.database import SessionLocal
from app.routers.uebergaben import RICHTUNG
from app.services.uebergabe_befund import beleg_beurteilen
from app.services.uebergabe_eingang import DatenbankLage


def main() -> int:
    wurzel = os.environ.get("UEBERGABEN_ORDNER")
    if not wurzel:
        print("UEBERGABEN_ORDNER ist nicht gesetzt", file=sys.stderr)
        return 2
    ordner = Path(wurzel) / RICHTUNG
    if not ordner.is_dir():
        print(f"Kein Belegordner: {ordner}", file=sys.stderr)
        return 2

    schluessel = os.environ.get("SCHLUESSEL_PFAD")
    schluessel_wurzel = Path(schluessel) if schluessel else None

    db = SessionLocal()
    abgelehnt = 0
    try:
        for datei in sorted(ordner.glob("*.json")):
            urteil = beleg_beurteilen(
                datei.read_bytes(), DatenbankLage(db), schluessel_wurzel=schluessel_wurzel,
            )
            if urteil.bereits_verarbeitet:
                stand = "bereits verarbeitet"
            elif urteil.angenommen:
                stand = (
                    f"angenommen, {urteil.zahl_gutschriften} Gutschrift(en), "
                    f"{urteil.summe_netto} netto"
                )
            else:
                abgelehnt += 1
                erster = urteil.feststellungen[0]
                stand = f"abgelehnt: {erster.code} bei {erster.pfad}"
            print(f"{datei.name}: {stand}")
    finally:
        # Nichts zu committen: dieses Skript schreibt nicht.
        db.rollback()
        db.close()
    return 1 if abgelehnt else 0


if __name__ == "__main__":
    sys.exit(main())
