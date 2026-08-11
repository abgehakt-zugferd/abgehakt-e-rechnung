"""Versionsvergleich (#120). Zeichenkettenvergleich waere falsch: '0.10.0' < '0.9.0'."""
import pytest

from app.services.update_check import is_newer_version


@pytest.mark.parametrize("latest,current,erwartet", [
    ("1.0.1", "1.0.0", True),
    ("0.10.0", "0.9.0", True),      # genau der Fall, den ein String-Vergleich verdreht
    ("1.0.0", "1.0.0", False),
    ("1.0.0", "1.0.1", False),
    ("v1.2.0", "1.1.0", True),      # 'v'-Praefix am Git-Tag
    ("1.2.0", "1.2.0rc1", True),    # Vorabversion ist aelter als das Release
])
def test_vergleich(latest, current, erwartet):
    assert is_newer_version(latest, current) is erwartet


def test_dev_wird_nie_verglichen():
    assert is_newer_version("9.9.9", "dev") is False


def test_unlesbare_version_ist_kein_update():
    """Fail-safe: Was wir nicht verstehen, loest keinen Hinweis aus."""
    assert is_newer_version("nicht-eine-version", "1.0.0") is False


def test_packaging_steht_in_den_laufzeit_abhaengigkeiten():
    """Regressionsschutz: packaging lag NUR als pytest-Abhaengigkeit im Lock und
    fehlte damit im Prod-Image (Prod-Stage installiert mit --no-group test).

    Ein blosses `import packaging` waere hier FALSCH-GRUEN: Der Testcontainer
    installiert MIT --group test, dort ist packaging als pytest-Abhaengigkeit
    ohnehin da. Bewiesen wird deshalb die Deklaration; das Prod-Image selbst
    prueft Schritt 4 dieses Tasks.
    """
    import tomllib
    from pathlib import Path

    pyproject = Path("/app/pyproject.toml")
    if not pyproject.exists():
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    deps = tomllib.loads(pyproject.read_text())["project"]["dependencies"]
    assert any(d.startswith("packaging") for d in deps), \
        "packaging muss LAUFZEIT-Abhaengigkeit sein, nicht nur Test-Abhaengigkeit"
