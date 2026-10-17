"""Ohne die Vektoren wird hier nichts gesammelt.

Ein Skip waere in diesem Repository ein Fehlschlag (Skip-Guard in
.githooks/pre-push und in der CI), und ein fehlender Ordner ist kein
fehlgeschlagener Test. Nicht gesammelt heisst: der Lauf behauptet nicht,
gemessen zu haben. Gesagt wird es trotzdem, im Kopf jedes Laufs.
"""

import json

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
def schluesselordner(vektoren, tmp_path_factory):
    """Die Probeschluessel des Vektorordners, mit Beiblättern dieser Fassung.

    Die Beiblätter dort tragen noch Felder aus der Zeit vor dem geschlossenen
    Feldbestand (abgehakt#166: hinweis, probe, warum_probe); der Leser verwirft
    solche Schluessel als SCHLUESSEL_UNBEKANNT, und dieser Befund wuerde jede
    spätere Ablehnung ueberdecken. Der Vektorordner gehoert keinem Empfaenger
    allein und ist hier nur lesend eingehaengt, deshalb baut dieser Fixture die
    Beiblätter zur Laufzeit neu: aus genau den Angaben, die § 6 zulaesst, am
    selben .pub. Nichts davon landet im Repositorium. Gemessen wird der Leser
    und sein Befundcode, nicht der Autor der Beiblätter.
    """
    quelle = vektoren.parent / "schluessel"
    ziel = tmp_path_factory.mktemp("schluessel")
    erlaubt = (
        "schluessel_id", "absender", "verfahren",
        "gueltig_von", "gueltig_bis", "notizen",
    )
    for beiblatt in sorted(quelle.glob("*/*.json")):
        angaben = json.loads(beiblatt.read_text(encoding="utf-8"))
        ordner = ziel / beiblatt.parent.name
        ordner.mkdir()
        (ordner / beiblatt.name).write_text(
            json.dumps({name: angaben[name] for name in angaben if name in erlaubt}),
            encoding="utf-8",
        )
        (ordner / f"{beiblatt.stem}.pub").write_bytes(
            (beiblatt.parent / f"{beiblatt.stem}.pub").read_bytes()
        )
    return ziel
