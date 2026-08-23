"""B2 §5: Die App-Engine MUSS fail-closed sein — fehlt APP_DATABASE_URL, gibt es
KEINEN stillen Fallback auf DATABASE_URL (das wuerde Least-Privilege aushebeln).

Statt importlib.reload(app.database) laufen die Import-Pruefungen in einem
Subprozess: reload erzeugt eine neue Base-Klasse, waehrend Modelle an der alten
haengen bleiben — das machte den vollen Suite-Lauf fragil (siehe frueherer
Kommentar in dieser Datei, Issue #36).
"""
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _import_database(**env) -> subprocess.CompletedProcess[str]:
    """Isolierter Import von app.database mit ueberschriebenen Umgebungsvariablen."""
    proc_env = os.environ.copy()
    proc_env.update(env)
    script = """
import sys
try:
    import app.database as db
except RuntimeError as exc:
    print(str(exc), file=sys.stderr)
    sys.exit(2)
print(db.engine.url.username)
"""
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(BACKEND),
        env=proc_env,
        capture_output=True,
        text=True,
    )


def test_missing_app_database_url_raises():
    """Fehlt APP_DATABASE_URL, MUSS die App-Engine beim Import fehlschlagen."""
    result = _import_database(
        DATABASE_URL="postgresql://abgehakt_admin:changeme@localhost:5432/abgehakt",
        APP_DATABASE_URL="",
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "APP_DATABASE_URL" in result.stderr


def test_app_engine_uses_app_database_url():
    """Mit APP_DATABASE_URL MUSS die Engine als abgehakt_app verbinden."""
    result = _import_database(
        DATABASE_URL="postgresql://abgehakt_admin:changeme@localhost:5432/abgehakt",
        APP_DATABASE_URL="postgresql://abgehakt_app:pw@localhost:5432/abgehakt",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "abgehakt_app"
