"""Deklarierte Abhängigkeiten ≡ installierte Umgebung (#105 Phase 1).

Gelesen wird die Deklaration aus dem IMAGE (/app/pyproject.toml, /app/uv.lock),
nicht vom Host. Der Test prüft also, was wirklich gebaut wurde.

Was dieser Test NICHT leistet: Er beweist nicht, dass der Lock beim Bauen
respektiert wurde — das leistet `uv sync --locked` im Dockerfile. Und er beweist
nicht, dass die Versionen die *richtigen* sind.
"""

import re
import tomllib
from importlib.metadata import PackageNotFoundError, distributions, version
from pathlib import Path

import pytest

PYPROJECT = Path("/app/pyproject.toml")
UV_LOCK = Path("/app/uv.lock")

# Stammen aus python:3.11-slim und werden nicht von uv verwaltet.
UNMANAGED = {"pip", "setuptools", "wheel"}


def _normalize(name: str) -> str:
    """PEP 503: kleinschreiben, Läufe aus -_. zu einem - zusammenziehen.

    Nötig, weil installiert `pydantic_core` heißt, im Lock aber `pydantic-core`.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def _parse_pin(spec: str) -> tuple[str, str]:
    """'uvicorn[standard]==0.32.1' -> ('uvicorn', '0.32.1').

    Die Reihenfolge ist wichtig: ERST an '==' trennen, DANN die Extras abstreifen.
    Umgekehrt liefert spec.split('[')[0] bei einem Pin ohne Extras den kompletten
    String samt Version, und der Name wird zu 'fastapi==0.115.5'.
    """
    assert "==" in spec, f"Kein exakter Pin: {spec!r}"
    name_with_extras, pinned = spec.split("==", 1)
    return name_with_extras.split("[", 1)[0].strip(), pinned.strip()


@pytest.fixture(scope="module")
def declared() -> dict[str, str]:
    """Direkte Pins aus pyproject.toml, Namen normalisiert."""
    assert PYPROJECT.is_file(), f"{PYPROJECT} fehlt im Image"
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))

    runtime = data["project"]["dependencies"]
    test_group = data["dependency-groups"]["test"]
    assert runtime, "[project].dependencies ist leer"
    assert test_group, "[dependency-groups].test ist leer"

    pins: dict[str, str] = {}
    for spec in [*runtime, *test_group]:
        name, pinned = _parse_pin(spec)
        pins[_normalize(name)] = pinned
    return pins


@pytest.fixture(scope="module")
def locked() -> dict[str, str]:
    """Alle Pakete aus uv.lock, Namen normalisiert.

    Der Lock trägt [[package]]-Blöcke, tomllib liefert daher den Schlüssel
    'package' (SINGULAR, Liste) — nicht 'packages'.
    """
    assert UV_LOCK.is_file(), f"{UV_LOCK} fehlt im Image"
    data = tomllib.loads(UV_LOCK.read_text(encoding="utf-8"))
    packages = data["package"]
    assert packages, "uv.lock enthält keine Pakete"
    return {_normalize(p["name"]): p["version"] for p in packages}


def test_jeder_direkte_pin_ist_in_genau_dieser_version_installiert(declared):
    geprueft = 0
    for name, pinned in declared.items():
        try:
            installiert = version(name)
        except PackageNotFoundError:
            pytest.fail(f"{name}=={pinned} ist deklariert, aber nicht installiert")
        assert installiert == pinned, (
            f"{name}: deklariert {pinned}, installiert {installiert}"
        )
        geprueft += 1

    # Schutz gegen stilles Leerlaufen: greift das Parsen daneben, iteriert die
    # Schleife über nichts und der Test wäre grün, ohne etwas geprüft zu haben.
    assert geprueft >= 18, f"Nur {geprueft} Pins geprüft — Parsing kaputt?"


def test_jede_installierte_distribution_steht_im_lock(locked):
    geprueft = 0
    for dist in distributions():
        raw = dist.metadata["Name"]
        if raw is None:
            continue
        name = _normalize(raw)
        if name in UNMANAGED:
            continue
        assert name in locked, f"{name} ist installiert, steht aber nicht in uv.lock"
        assert dist.version == locked[name], (
            f"{name}: installiert {dist.version}, im Lock {locked[name]}"
        )
        geprueft += 1

    # Schwelle bewusst nahe an der Wirklichkeit: der Lock hat 45 Eintraege, davon sind
    # der Projekt-Wurzeleintrag und das win32-markierte colorama nie installiert, drei
    # weitere (pip/setuptools/wheel) sind ausgenommen — es bleiben rund 43. Eine zu
    # niedrige Schwelle (etwa 18) wuerde ein Dutzend fehlender Pakete durchlassen und
    # damit genau das Leerlaufen erlauben, gegen das sie schuetzen soll.
    assert geprueft >= 35, f"Nur {geprueft} Distributionen geprüft — Parsing kaputt?"
