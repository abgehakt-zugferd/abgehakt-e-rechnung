"""Was ausgeliefert wird, startet einen Produktionsserver (10.08.2026).

Gefunden beim Nachsehen, warum sich der Stack "aufhängt". Im Log der laufenden
Installation stand:

    INFO:     Started reloader process [1] using WatchFiles
    WARNING:  WatchFiles detected changes in 'tests/test_update_link_safety.py'.
              Reloading...

Der Entrypoint startete `uvicorn --reload`, den Entwicklungsschalter, und zwar in
dem Befehl, den jede Installation ausführt. Das kostet dreierlei:

1. Einen zweiten Prozess samt Dateiwächter über das ganze Arbeitsverzeichnis.
2. Einen Neustart des Servers, sobald irgendeine Python-Datei geschrieben wird.
   Im Beispiel oben war es eine Testdatei, nicht einmal Anwendungscode.
3. Einen Elternprozess, der sich beim Stoppen nicht beendet. Docker wartet die
   volle Frist ab und schießt ihn dann ab: Exit 137 hinter einem sauberen
   "Application shutdown complete". Das ist das vermeintliche Aufhängen.

Entwicklung braucht das Nachladen weiterhin und bekommt es über
`docker-compose.dev.yml`, das dem Entrypoint uvicorn-Argumente mitgibt. Der
zweite Test sichert genau diese Durchreichung: ohne sie wäre die Auslieferung
zwar sauber, die Entwicklung aber still kaputt.

Gelesen wird die Datei aus dem Abbild, nicht aus dem Arbeitsverzeichnis. Das ist
der Unterschied zwischen "im Repo steht das Richtige" und "im Container läuft das
Richtige", und nur der zweite Satz zählt.
"""
import re
from pathlib import Path

ENTRYPOINT = Path(__file__).resolve().parents[1] / "entrypoint.sh"


def _zeilen() -> list[str]:
    text = ENTRYPOINT.read_text(encoding="utf-8")
    return [z for z in text.splitlines() if z.strip() and not z.lstrip().startswith("#")]


def _uvicorn_zeile() -> str:
    treffer = [z for z in _zeilen() if "uvicorn" in z]
    assert len(treffer) == 1, f"Genau eine uvicorn-Zeile erwartet, gefunden: {treffer}"
    return treffer[0]


def test_auslieferung_startet_ohne_nachladen():
    """Geprüft werden die ausgeführten Zeilen, nicht die Datei: Der Kommentar über
    der Startzeile erklärt, warum `--reload` dort nicht mehr steht, und darf das
    Wort deshalb nennen."""
    treffer = [z for z in _zeilen() if "--reload" in z]

    assert not treffer, (
        "Der ausgelieferte Startbefehl enthält den Entwicklungsschalter --reload: "
        f"{treffer}. Er gehört nach docker-compose.dev.yml, nicht in den Entrypoint."
    )


def test_entrypoint_reicht_zusatzargumente_durch():
    """Sonst kann die Entwicklung das Nachladen nicht mehr anschalten, und der
    Test oben wäre grün, weil das Nachladen ÜBERALL fehlt."""
    assert '"$@"' in _uvicorn_zeile(), (
        "Die uvicorn-Zeile reicht $@ nicht durch. docker-compose.dev.yml hängt "
        "--reload an den Entrypoint an; ohne Durchreichung verpufft das."
    )


def test_entrypoint_startet_ueberhaupt_einen_server():
    """Gegenprobe zu Test 1: Wer die uvicorn-Zeile löscht, macht ihn ebenfalls grün."""
    zeile = _uvicorn_zeile()

    assert "app.main:app" in zeile
    assert "--port 3000" in zeile
    assert zeile.lstrip().startswith("exec "), (
        "Ohne exec bleibt die Shell als PID 1 stehen und reicht das Stoppsignal "
        "nicht an uvicorn weiter."
    )


def test_migrationen_laufen_vor_dem_server():
    """Der Grund, warum docker-compose.dev.yml den Entrypoint-Pfad wiederholt,
    statt einfach `command: uvicorn ...` zu setzen: eine ersetzte Startzeile
    würde die Migrationen überspringen, und das fiele erst beim ersten
    Datenbankzugriff auf."""
    zeilen = _zeilen()
    alembic = [i for i, z in enumerate(zeilen) if re.search(r"\balembic\b.*upgrade", z)]
    uvicorn = [i for i, z in enumerate(zeilen) if "uvicorn" in z]

    assert alembic, "Der Entrypoint führt keine Migrationen mehr aus."
    assert alembic[0] < uvicorn[0], "Die Migrationen laufen nach dem Serverstart."
