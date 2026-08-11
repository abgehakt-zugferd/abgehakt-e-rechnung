"""B2 §5: Die App-Engine MUSS fail-closed sein — fehlt APP_DATABASE_URL, gibt es
KEINEN stillen Fallback auf DATABASE_URL (das würde Least-Privilege aushebeln)."""
import importlib

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _base_wiederherstellen():
    """`importlib.reload(app.database)` erzeugt eine NEUE `Base`-Klasse — mit
    leerer `MetaData`.

    Die Modellmodule liegen zu diesem Zeitpunkt längst in `sys.modules` und
    bleiben an der ALTEN `Base` registriert; ein erneutes `import app.models`
    ist ein No-op und registriert nichts nach. Wer danach `Base.metadata` liest,
    sieht eine Datenbank ohne Tabellen — und das Aufräumen am Testende macht es
    nicht besser, es erzeugt eine dritte, ebenso leere `Base`.

    Sichtbar wurde das über `test_migrationskette.py`: dort vergleicht
    `alembic check` die Migration gegen `Base.metadata`. Ohne diese Fixture ist
    der Test **im Gesamtlauf rot und allein grün** — nachgemessen, nicht
    vermutet (Fixture aus ⇒ 1 failed, Fixture an ⇒ 612 passed). Ein Zweierpaar
    aus dieser Datei und dem Migrationstest reicht zum Nachstellen NICHT; es
    braucht den vollen Lauf. Wer hier etwas ändert, prüft entsprechend gegen die
    ganze Suite, nicht gegen die beiden Dateien.
    """
    import app.database
    original = app.database.Base
    yield
    app.database.Base = original


def _reload_database_with(monkeypatch, **env):
    monkeypatch.setattr("app.config.get_settings", lambda: Settings(**env))
    import app.database
    return importlib.reload(app.database)


def test_missing_app_database_url_raises(monkeypatch):
    """Fehlt APP_DATABASE_URL, MUSS die App-Engine beim Import fehlschlagen."""
    with pytest.raises(RuntimeError, match="APP_DATABASE_URL"):
        _reload_database_with(
            monkeypatch,
            database_url="postgresql://abgehakt_admin:changeme@localhost:5432/abgehakt",
            app_database_url="",
        )


def test_app_engine_uses_app_database_url(monkeypatch):
    """Mit APP_DATABASE_URL MUSS die Engine als abgehakt_app verbinden."""
    mod = _reload_database_with(
        monkeypatch,
        database_url="postgresql://abgehakt_admin:changeme@localhost:5432/abgehakt",
        app_database_url="postgresql://abgehakt_app:pw@localhost:5432/abgehakt",
    )
    assert mod.engine.url.username == "abgehakt_app"
    # Aufräumen: Modul mit echten Settings neu laden, damit Folgetests die reale Engine sehen.
    monkeypatch.undo()
    importlib.reload(mod)
