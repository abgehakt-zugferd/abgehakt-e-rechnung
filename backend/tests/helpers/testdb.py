"""Name der Test-Datenbank (und je Prozess abgeleiteter Namen im Cluster).

Mehrere pytest-Prozesse gegen denselben Postgres (z. B. die Mutationspruefung)
duerfen einander nicht die Datenbank loeschen.

- `ABGEHAKT_TEST_DB` setzt den Namen (Standard: `abgehakt_test`).
- `ABGEHAKT_TEST_DB_JE_PROZESS=1` haengt `_<pid>` an.

Der Name geht per f-String in SQL (`CREATE DATABASE`, `DROP DATABASE`). Deshalb
nur einfache, kleingeschriebene Bezeichner; alles andere scheitert laut.
"""
import os
import re
from collections.abc import Mapping

STANDARD_NAME = "abgehakt_test"
VARIABLE_NAME = "ABGEHAKT_TEST_DB"
VARIABLE_JE_PROZESS = "ABGEHAKT_TEST_DB_JE_PROZESS"

# Hoechstlaenge eines Postgres-Bezeichners (NAMEDATALEN - 1).
_MAX_LAENGE = 63
_BEZEICHNER = re.compile(r"[a-z_][a-z0-9_]*")


def _je_prozess_aktiv(umgebung: Mapping[str, str]) -> bool:
    return umgebung.get(VARIABLE_JE_PROZESS) == "1"


def _pruefe(name: str) -> str:
    if len(name) > _MAX_LAENGE or not _BEZEICHNER.fullmatch(name):
        raise ValueError(
            f"{VARIABLE_NAME}={name!r} ist kein gueltiger Postgres-Bezeichner "
            f"(erlaubt: a-z, 0-9, _, nicht mit Ziffer beginnend, hoechstens "
            f"{_MAX_LAENGE} Zeichen inklusive eines Prozess-Suffixes)."
        )
    return name


def je_prozess(
    name: str, umgebung: Mapping[str, str] | None = None, pid: int | None = None
) -> str:
    """`name` unveraendert, bei `ABGEHAKT_TEST_DB_JE_PROZESS=1` mit `_<pid>`."""
    umgebung = os.environ if umgebung is None else umgebung
    if _je_prozess_aktiv(umgebung):
        return f"{name}_{os.getpid() if pid is None else pid}"
    return name


def datenbankname(
    umgebung: Mapping[str, str] | None = None, pid: int | None = None
) -> str:
    umgebung = os.environ if umgebung is None else umgebung
    basis = umgebung[VARIABLE_NAME] if VARIABLE_NAME in umgebung else STANDARD_NAME
    return _pruefe(je_prozess(basis, umgebung, pid))
