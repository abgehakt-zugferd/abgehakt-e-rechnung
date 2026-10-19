"""Ohne die Vektoren wird hier nichts gesammelt.

Ein Skip waere in diesem Repository ein Fehlschlag (Skip-Guard in
.githooks/pre-push und in der CI), und ein fehlender Ordner ist kein
fehlgeschlagener Test. Nicht gesammelt heisst: der Lauf behauptet nicht,
gemessen zu haben. Gesagt wird es trotzdem, im Kopf jedes Laufs.
"""

import pytest

from tests.helpers.formatvektoren import vektorordner

collect_ignore_glob = [] if vektorordner() else ["test_*.py"]


@pytest.fixture(autouse=True)
def als_testinstanz(monkeypatch):
    """Die Vektoren sind mit Probeschluesseln signiert (`-probe-`), und die nimmt
    eine Echtinstallation nicht an (§ 6). Gemessen wird deshalb als Testinstanz -
    genau die Umgebung, in der eine Kettenprobe stattfindet."""
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "installation_mode", "testinstanz")


@pytest.fixture(scope="session")
def vektoren():
    ordner = vektorordner()
    assert ordner is not None, "ohne Vektoren wird hier nicht gesammelt"
    return ordner / "vektoren"


@pytest.fixture(scope="session")
def protokoll(vektoren):
    import json

    return json.loads((vektoren.parent / "protokoll.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def schluesselordner(vektoren):
    """Die Probeschluessel des Vektorordners, lesend direkt.

    Bis 1.6 trugen die Beiblätter dort noch Felder aus der Zeit vor dem
    geschlossenen Feldbestand (hinweis, probe, warum_probe); der Leser
    verwirft solche Schluessel als SCHLUESSEL_UNBEKANNT, und dieser Befund
    wuerde jede spaetere Ablehnung ueberdecken. Deshalb baute eine Fixture
    sie zur Laufzeit neu (abgehakt#159). Seit 1.7 tragen die Beiblätter nur
    die Pflichtfelder plus notizen, wie § 6 es verlangt, und werden direkt
    gelesen: Der Vektorordner gehoert keinem Empfaenger allein und ist hier
    nur lesend eingehaengt, nichts davon landet im Repositorium.
    """
    return vektoren.parent / "schluessel"
