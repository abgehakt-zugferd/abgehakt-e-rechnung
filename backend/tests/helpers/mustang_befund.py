"""Gemeinsamer Helfer fuer Tests, die `mustang.validate` auswerten.

Linie (#252): ohne ausfuehrbares Mustang wird AUSDRUECKLICH uebersprungen, mit
derselben Begruendung wie bei den `skipif(not jar_available())`-Tests. Der
Skip ist kein Freispruch: das CI-Gate (`.github/workflows/tdd.yml`) wertet jeden
Skip im Test-Abbild als Fehlschlag. Ein leeres `is_valid=False` wird so nie
als „XML ungueltig" gelesen, obwohl nichts gemessen wurde.
"""
import pytest


def _ungemessen(befund: dict) -> None:
    if befund.get("nicht_ausfuehrbar"):
        pytest.skip(f"Mustang fehlt, nicht gemessen: {befund.get('grund', '')}")


def gueltig(befund: dict, detail=None) -> None:
    """Sichert zu, dass Mustang die Pruefung bestanden hat.

    Nicht ausfuehrbar: Skip mit Grund. Ungueltig: Fehlschlag mit `detail`
    (oder den Mustang-Fehlern, wenn keines angegeben ist).
    """
    _ungemessen(befund)
    assert befund["is_valid"], detail if detail is not None else befund["errors"]


def ungueltig(befund: dict, detail=None) -> None:
    """Sichert zu, dass Mustang die Pruefung ausgefuehrt und verworfen hat."""
    _ungemessen(befund)
    assert not befund["is_valid"], detail if detail is not None else befund["raw"]
