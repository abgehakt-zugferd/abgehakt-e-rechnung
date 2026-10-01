"""Architekturregel #129: kein nacktes Prozessdatum unter backend/app/."""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
ERLAUBT = {APP / "zeit.py"}


def _module_alias(knoten: ast.AST) -> str | None:
    """Name des datetime-Moduls bei Attribute-Ketten (dt.date / dt.datetime)."""
    if isinstance(knoten, ast.Name):
        return knoten.id
    return None


def _gebundenheiten(baum: ast.AST) -> tuple[set[str], set[str], set[str]]:
    """date-Aliase, datetime-Aliase, Modul-Aliase fuer import datetime."""
    date_namen: set[str] = set()
    datetime_namen: set[str] = set()
    modul_namen: set[str] = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.ImportFrom) and knoten.module == "datetime":
            for alias in knoten.names:
                lokal = alias.asname or alias.name
                if alias.name == "date":
                    date_namen.add(lokal)
                elif alias.name == "datetime":
                    datetime_namen.add(lokal)
        elif isinstance(knoten, ast.Import):
            for alias in knoten.names:
                if alias.name == "datetime":
                    modul_namen.add(alias.asname or alias.name)
    return date_namen, datetime_namen, modul_namen


def _ist_date_empfänger(
    wert: ast.AST, date_namen: set[str], modul_namen: set[str],
) -> bool:
    if isinstance(wert, ast.Name) and wert.id in date_namen:
        return True
    if (
        isinstance(wert, ast.Attribute)
        and wert.attr == "date"
        and _module_alias(wert.value) in modul_namen
    ):
        return True
    return False


def _ist_datetime_empfänger(
    wert: ast.AST, datetime_namen: set[str], modul_namen: set[str],
) -> bool:
    if isinstance(wert, ast.Name) and wert.id in datetime_namen:
        return True
    if (
        isinstance(wert, ast.Attribute)
        and wert.attr == "datetime"
        and _module_alias(wert.value) in modul_namen
    ):
        return True
    return False


def _now_ohne_zeitzone(aufruf: ast.Call) -> bool:
    """True bei now() ohne Argument oder mit None / tz=None."""
    if not aufruf.args and not aufruf.keywords:
        return True
    if len(aufruf.args) == 1 and not aufruf.keywords:
        arg = aufruf.args[0]
        return isinstance(arg, ast.Constant) and arg.value is None
    if not aufruf.args and len(aufruf.keywords) == 1:
        kw = aufruf.keywords[0]
        return (
            kw.arg == "tz"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is None
        )
    return False


def funde_in_quelle(quelle: str, rel: str = "probe.py") -> list[str]:
    """Verbotene Aufrufe in Quelltext; jeder Treffer als rel:zeile: ausschnitt."""
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return []

    date_namen, datetime_namen, modul_namen = _gebundenheiten(baum)
    zeilen = quelle.splitlines()
    funde: list[str] = []

    for knoten in ast.walk(baum):
        if not isinstance(knoten, ast.Call):
            continue
        func = knoten.func
        if not isinstance(func, ast.Attribute):
            continue
        attr = func.attr
        empfaenger = func.value
        verboten = False
        if attr == "today":
            verboten = (
                _ist_date_empfänger(empfaenger, date_namen, modul_namen)
                or _ist_datetime_empfänger(empfaenger, datetime_namen, modul_namen)
            )
        elif attr == "utcnow":
            verboten = _ist_datetime_empfänger(
                empfaenger, datetime_namen, modul_namen,
            )
        elif attr == "now":
            verboten = (
                _ist_datetime_empfänger(empfaenger, datetime_namen, modul_namen)
                and _now_ohne_zeitzone(knoten)
            )
        if not verboten:
            continue
        zeile = knoten.lineno
        ausschnitt = zeilen[zeile - 1].strip() if 1 <= zeile <= len(zeilen) else ""
        funde.append(f"{rel}:{zeile}: {ausschnitt}")
    return funde


def _treffer_in(pfad: Path) -> list[str]:
    quelle = pfad.read_text(encoding="utf-8")
    rel = str(pfad.relative_to(APP.parent))
    return funde_in_quelle(quelle, rel=rel)


def test_kein_nacktes_prozessdatum_ausser_in_zeit_modul():
    dateien = sorted(p for p in APP.rglob("*.py") if p not in ERLAUBT)
    assert dateien, "kein Suchraum unter app/: der Waechter prueft nichts"

    treffer = [t for p in dateien for t in _treffer_in(p)]
    assert not treffer, (
        "Nacktes Prozessdatum unter app/ (nur app/zeit.py darf die Uhr lesen):\n"
        + "\n".join(treffer)
    )


@pytest.mark.parametrize(
    "quelle",
    [
        "from datetime import date as D\nD.today()\n",
        "from datetime import datetime\ndatetime.utcnow()\n",
        "from datetime import datetime\ndatetime.now(None)\n",
        "from datetime import datetime\ndatetime.now(tz=None)\n",
        "from datetime import datetime\ndatetime.now(\n# Kommentar\n)\n",
        'from datetime import date\nmarker = "#"; tag = date.today()\n',
        "import datetime as dt\ndt.datetime.now()\n",
        "import datetime as dt\ndt.date.today()\n",
    ],
)
def test_architektur_erkennt_umgehungen(quelle):
    funde = funde_in_quelle(quelle)
    assert funde, f"Umgehung nicht erkannt:\n{quelle}"


@pytest.mark.parametrize(
    "quelle",
    [
        'hinweis = "date.today()"\n',
        "# date.today()\n",
        "from datetime import datetime, timezone\ndatetime.now(timezone.utc)\n",
        "from datetime import datetime\nfrom zoneinfo import ZoneInfo\n"
        "datetime.now(tz=ZoneInfo('Europe/Berlin'))\n",
        "import time\ntime.time()\n",
    ],
)
def test_architektur_laesst_erlaubtes_durch(quelle):
    funde = funde_in_quelle(quelle)
    assert not funde, f"Falscher Alarm:\n{quelle}\n{funde}"
