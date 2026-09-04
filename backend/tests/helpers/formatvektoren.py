"""Wo die Formatvektoren liegen, und ob sie ueberhaupt da sind.

Die Vektoren sind Dateien, kein Modul: sie liegen ausserhalb dieses Repositoriums,
werden nicht mitgeliefert und werden nicht importiert. Gemessen wird gegen die
Bytes, damit aus zwei unabhaengigen Umsetzungen nicht wieder eine wird.

Pfad aus der Umgebungsvariablen `UEBERGABE_VEKTOREN`. **Bewusst ohne Vorgabe:**
Name und Vorgabepfad, die das Uebergabepapier dafuer nennt, tragen den Namen des
Betreibers, und dieses Repositorium ist oeffentlich (Waechter: der Firmennamen-Test
in tests/). Wer misst, setzt den Pfad in seiner Umgebung; die
kanonische Baseline reicht ihn in den Container durch (backend/run-tests.sh).

Ist er nicht gesetzt, laufen die Tests unter `tests/vektoren/` nicht, und
`pytest_terminal_summary` in tests/conftest.py sagt das am Ende jedes Laufs.
"""

import os
from pathlib import Path
from typing import Optional

UMGEBUNGSVARIABLE = "UEBERGABE_VEKTOREN"


def gewuenschter_pfad() -> Optional[Path]:
    roh = os.environ.get(UMGEBUNGSVARIABLE, "").strip()
    return Path(roh) if roh else None


def vektorordner() -> Optional[Path]:
    """Der Ordner, oder None, wenn dort kein `protokoll.json` liegt."""
    pfad = gewuenschter_pfad()
    if pfad is None:
        return None
    return pfad if (pfad / "protokoll.json").is_file() else None
