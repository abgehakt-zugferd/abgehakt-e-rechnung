"""Tests für die Startup-Validierung (main.validate_startup_config + Lifespan).

Regeln:
  - Fehlt SECRET_KEY → RuntimeError (Boot bricht ab, fail-fast).
  - SECRET_KEY < 32 Zeichen → UserWarning (aber kein Abbruch).
  - Gültiger SECRET_KEY → kein Fehler, keine Warnung.
"""
import pytest
from types import SimpleNamespace

from app.main import validate_startup_config


def test_missing_secret_key_raises():
    """Letzte Reißleine: normal holen die Settings den Schlüssel aus
    `storage/secret.key` (#99 §5.4) — greift der Check, ist das storage-Volume
    kaputt, und genau darauf zeigt die Meldung."""
    with pytest.raises(RuntimeError, match="secret.key"):
        validate_startup_config(SimpleNamespace(secret_key="", storage_path="/app/storage"))


def test_valid_secret_key_passes():
    # 40 Zeichen: kein RuntimeError, keine Warnung
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # jede Warnung würde den Test failen lassen
        validate_startup_config(SimpleNamespace(secret_key="x" * 40))


def test_short_secret_key_warns():
    with pytest.warns(UserWarning):
        validate_startup_config(SimpleNamespace(secret_key="short"))


from fastapi.testclient import TestClient
from app.config import get_settings
from app.main import app


def test_lifespan_blocks_boot_without_secret_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "secret_key", "")
    with pytest.raises(RuntimeError):
        with TestClient(app):  # Context-Manager triggert den Lifespan-Startup
            pass


def test_lifespan_boots_with_secret_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "secret_key", "x" * 40)
    with TestClient(app):  # kein Fehler → Boot erfolgreich
        pass
