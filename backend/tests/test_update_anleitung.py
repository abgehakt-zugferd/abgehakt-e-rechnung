"""Update-Anleitung (#120). Sichern kommt ZUERST, und storage/ gehoert dazu:
db-backup haengt nur ./backups ein, ./storage ist in KEINEM Backup (#121).
Ein reiner Dump stellt die archivierten Rechnungs-PDFs nicht wieder her.

Der zweite Punkt (2026-08-11) ist der Aktualisierungsbefehl selbst. Die
Anleitung nannte `docker compose pull` — der Dienst `app` wird aber aus
`./backend` GEBAUT und hat kein veroeffentlichtes Abbild. `pull` ueberspringt
ihn wortlos ("app Skipped  No image to be pulled") und endet mit Rueckgabewert
0. Wer der Anleitung folgte, hatte danach dieselbe Version wie vorher, ohne
eine einzige Fehlermeldung, und der Hinweis nörgelte weiter.
"""
import re

from fastapi.testclient import TestClient

from app.main import app


def _anleitung() -> str:
    with TestClient(app, follow_redirects=False) as c:
        return c.get("/updates/anleitung").text


def _befehle() -> str:
    """Nur die Blöcke zum Abtippen. Geprüft wird, was jemand kopiert — im
    Fließtext darf `pull` sehr wohl vorkommen, denn genau das versuchen die
    meisten aus Gewohnheit, und die Anleitung muss sagen, warum es nicht reicht."""
    return "\n".join(re.findall(r"<pre>(.*?)</pre>", _anleitung(), re.S))


def test_anleitung_nennt_sicherung_vor_dem_update():
    text = _anleitung()
    backup = text.index("/backup.sh")
    aktualisieren = text.index("git fetch")
    assert backup < aktualisieren, "Sicherung muss VOR dem Update stehen"


def test_anleitung_sichert_auch_storage():
    assert "storage" in _anleitung()


def test_anleitung_baut_das_abbild_neu():
    """`build` ist der einzige Weg, an dem neuer Code in die Installation kommt."""
    befehle = _befehle()
    assert "--build" in befehle or "docker compose build" in befehle, (
        "Ohne Neubau bleibt die Installation auf der alten Fassung."
    )
    assert "docker compose pull" not in befehle, (
        "pull ueberspringt den gebauten Dienst `app` stillschweigend mit rc=0 — "
        "als Befehl zum Abtippen taeuscht er Erfolg vor, ohne etwas zu aendern."
    )


def test_anleitung_nennt_den_versionswechsel():
    """Ohne Wechsel auf den neuen Stand baut `build` nur die alte Fassung neu."""
    befehle = _befehle()
    assert "git fetch" in befehle
    assert "git checkout" in befehle


def test_anleitung_erklaert_den_fehlschlag():
    text = _anleitung()
    assert "docker compose logs" in text
    # Der Weg zurueck ist die Ruecksicherung, NICHT alembic downgrade.
    assert "downgrade" not in text.lower()
