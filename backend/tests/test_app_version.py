"""Versionsidentität (#120): ENV APP_VERSION, sonst die Datei VERSION, sonst 'dev'."""
import re
from pathlib import Path

from app.config import Settings, VERSIONSDATEI, version_aus_datei


def _dockerfile() -> str:
    pfad = Path("/app/Dockerfile")
    if not pfad.exists():
        pfad = Path(__file__).resolve().parents[1] / "Dockerfile"
    return pfad.read_text()


def test_ohne_datei_und_ohne_umgebung_bleibt_es_dev(tmp_path):
    assert version_aus_datei(tmp_path / "gibt-es-nicht") == "dev"


def test_app_version_kommt_aus_umgebung(monkeypatch):
    monkeypatch.setenv("APP_VERSION", "1.4.2")
    s = Settings(_env_file=None)
    assert s.app_version == "1.4.2"


def test_app_version_kommt_aus_der_versionsdatei_wenn_die_umgebung_schweigt(monkeypatch):
    """Der Weg, auf dem echte Installationen entstehen: Archiv herunterladen,
    entpacken, bauen. Dort gibt es kein Git und also auch kein `git describe` —
    ohne die Datei meldete jede Installation 'dev', und `compute_banner` gibt
    für 'dev' nichts zurück: die Update-Prüfung wäre auf jedem Rechner tot."""
    monkeypatch.delenv("APP_VERSION", raising=False)
    s = Settings(_env_file=None)
    assert s.app_version == VERSIONSDATEI.read_text(encoding="utf-8").strip()
    assert s.app_version != "dev"


def test_leere_umgebungsvariable_faellt_auf_die_datei_zurueck(monkeypatch):
    """Der Dockerfile-Fall: `ARG APP_VERSION=` ohne `--build-arg` setzt die
    Variable auf den leeren String. Gälte der als gesetzt, gewänne sie gegen die
    Datei und die Version wäre leer."""
    monkeypatch.setenv("APP_VERSION", "")
    s = Settings(_env_file=None)
    assert s.app_version == VERSIONSDATEI.read_text(encoding="utf-8").strip()


def test_versionsdatei_traegt_eine_dreistellige_versionsnummer():
    inhalt = VERSIONSDATEI.read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", inhalt), \
        f"VERSION muss X.Y.Z sein (Vergleich in is_newer_version), ist: {inhalt!r}"


def test_dockerfile_setzt_keinen_versions_default():
    """Stünde dort weiterhin `ARG APP_VERSION=dev`, setzte der Bau die Umgebungs-
    variable auf 'dev' — die Datei käme nie zum Zug, und der Fehler wäre unsichtbar,
    weil 'dev' eine gültig aussehende Antwort ist."""
    text = _dockerfile()
    assert text.count("ARG APP_VERSION") == 1
    assert re.search(r"^ARG APP_VERSION=\s*$", text, re.M), \
        "ARG APP_VERSION muss ohne Default stehen, sonst gewinnt er gegen VERSION"


def test_arg_app_version_steht_hinter_den_teuren_schichten():
    """Quell-Guard: Stünde ARG APP_VERSION vor 'uv sync', würde jedes Release
    JRE, Ghostscript, Mustang-JAR und alle Dependencies neu bauen."""
    text = _dockerfile()
    # Eindeutigkeit zuerst: gaebe es die Zeile mehrfach, wuerde ein Positions-
    # vergleich still das falsche Vorkommen treffen und der Guard waere wertlos.
    assert text.count("uv sync --locked --no-group test") == 1
    assert text.count("ARG APP_VERSION") == 1
    arg_pos = text.index("ARG APP_VERSION")
    sync_pos = text.index("uv sync --locked --no-group test")
    assert arg_pos > sync_pos, "ARG APP_VERSION muss NACH 'uv sync' stehen"
    assert re.search(r"^ENV APP_VERSION=\$\{APP_VERSION\}", text, re.M), \
        "ARG muss in ein ENV überführt werden, sonst sieht die Laufzeit es nicht"


def test_versionsdatei_liegt_im_baukontext():
    """`context: ./backend` — eine VERSION im Wurzelverzeichnis läge außerhalb
    und käme nie ins Image."""
    assert VERSIONSDATEI.name == "VERSION"
    assert VERSIONSDATEI.parent.name in ("backend", "app"), VERSIONSDATEI
