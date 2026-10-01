"""Architekturregel #129: kein nacktes Prozessdatum unter backend/app/."""
from __future__ import annotations

import ast
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
ERLAUBT = {APP / "zeit.py"}

VERBOTEN = re.compile(
    r"\b(?:date\.today|datetime\.today|datetime\.now)\s*\("
)


def _ist_kommentar_oder_docstring(quelle: str, offset: int, baum: ast.AST) -> bool:
    zeilenanfang = quelle.rfind("\n", 0, offset) + 1
    if "#" in quelle[zeilenanfang:offset]:
        return True

    zeile = quelle.count("\n", 0, offset) + 1
    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Expr):
            continue
        wert = knoten.value
        if not isinstance(wert, ast.Constant) or not isinstance(wert.value, str):
            continue
        start = knoten.lineno
        end = getattr(knoten, "end_lineno", start) or start
        if start <= zeile <= end:
            return True
    return False


def _treffer_in(pfad: Path) -> list[str]:
    quelle = pfad.read_text(encoding="utf-8")
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        baum = ast.Module(body=[], type_ignores=[])

    funde: list[str] = []
    for m in VERBOTEN.finditer(quelle):
        if m.group(0).startswith("datetime.now"):
            innen = quelle[m.end():].lstrip()
            if not innen.startswith(")"):
                continue  # datetime.now(tz=...) ist erlaubt
        if _ist_kommentar_oder_docstring(quelle, m.start(), baum):
            continue
        zeile = quelle.count("\n", 0, m.start()) + 1
        rel = pfad.relative_to(APP.parent)
        funde.append(f"{rel}:{zeile}: {quelle.splitlines()[zeile - 1].strip()}")
    return funde


def test_kein_nacktes_prozessdatum_ausser_in_zeit_modul():
    dateien = sorted(p for p in APP.rglob("*.py") if p not in ERLAUBT)
    assert dateien, "kein Suchraum unter app/: der Waechter prueft nichts"

    treffer = [t for p in dateien for t in _treffer_in(p)]
    assert not treffer, (
        "Nacktes Prozessdatum unter app/ (nur app/zeit.py darf die Uhr lesen):\n"
        + "\n".join(treffer)
    )
