"""Tests für die SMTP-/DATEV-Konfiguration (AppConfig in DB überlagert .env).

Abgedeckte Regeln / Bugfixes:
  - EffectiveSettings: DB-Werte überschreiben .env, None/leer fällt sauber auf .env zurück
  - smtp_use_tls=False in der DB wird respektiert (nicht durch .env-Default True überschrieben)
  - save_smtp: TLS lässt sich über die UI deaktivieren (abgewählte Checkbox → False)
  - save_smtp: leerer Host setzt auch den Port zurück (kein stale Port, der .env verdeckt)
  - Settings-Seite: TLS-Checkbox spiegelt den effektiven Wert wider
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models.app_config import AppConfig
from app.models.company import Company
from app.services.datev_email import EffectiveSettings, _get_effective_smtp_config


# ── Fake-DB (kein echtes PostgreSQL nötig) ──────────────────────────────────

class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDB:
    """Liefert je Modellklasse ein vorbereitetes Objekt (db.query.side_effect statt return_value — sonst liefert der Mock für jedes Modell dasselbe Objekt)."""

    def __init__(self, results=None):
        self._results = dict(results or {})
        self.commits = 0

    def query(self, model):
        return _FakeQuery(self._results.get(model))

    def add(self, obj):
        self._results[type(obj)] = obj

    def commit(self):
        self.commits += 1

    def refresh(self, obj):
        pass


def _base(**kwargs):
    defaults = dict(
        smtp_host="env-host.de", smtp_port=25, smtp_user="env-user",
        smtp_password="env-pw", smtp_from="env@from.de", smtp_use_tls=True,
        datev_bcc_email="env-datev@x.de",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ── EffectiveSettings: Merge-Logik ──────────────────────────────────────────

def test_effective_settings_db_overrides_env():
    db_cfg = SimpleNamespace(
        smtp_host="db-host.de", smtp_port=465, smtp_user="db-user",
        smtp_password="db-pw", smtp_from="db@from.de", smtp_use_tls=True,
        datev_bcc_email="db-datev@x.de",
    )
    eff = EffectiveSettings(db_cfg, _base())
    assert eff.smtp_host == "db-host.de"
    assert eff.smtp_port == 465
    assert eff.datev_bcc_email == "db-datev@x.de"


def test_effective_settings_falls_back_to_env_when_db_empty():
    db_cfg = SimpleNamespace(
        smtp_host=None, smtp_port=None, smtp_user=None,
        smtp_password=None, smtp_from=None, smtp_use_tls=None,
        datev_bcc_email=None,
    )
    eff = EffectiveSettings(db_cfg, _base())
    assert eff.smtp_host == "env-host.de"
    assert eff.smtp_port == 25
    assert eff.smtp_use_tls is True
    assert eff.datev_bcc_email == "env-datev@x.de"


def test_effective_settings_tls_false_in_db_is_respected():
    """smtp_use_tls=False darf NICHT durch den .env-Default True überschrieben werden."""
    db_cfg = SimpleNamespace(
        smtp_host="db-host.de", smtp_port=None, smtp_user=None,
        smtp_password=None, smtp_from=None, smtp_use_tls=False,
        datev_bcc_email=None,
    )
    eff = EffectiveSettings(db_cfg, _base(smtp_use_tls=True))
    assert eff.smtp_use_tls is False


def test_get_effective_smtp_config_without_db_returns_base():
    cfg = _get_effective_smtp_config(None)
    # ohne DB werden die .env-Settings verwendet (Objekt hat smtp_host-Attribut)
    assert hasattr(cfg, "smtp_host")


# ── save_smtp: TLS-Checkbox ──────────────────────────────────────────────────

def test_save_smtp_can_disable_tls():
    """Abgewählte Checkbox sendet kein Feld → smtp_use_tls muss False werden."""
    config = AppConfig(id=1, smtp_use_tls=True)
    db = _FakeDB({AppConfig: config})
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, follow_redirects=False)
        resp = client.post("/settings/smtp", data={
            "smtp_host": "smtp.example.de",
            "smtp_port": "587",
            "smtp_from": "a@b.de",
            # smtp_use_tls bewusst NICHT gesendet (Checkbox abgewählt)
        })
        assert resp.status_code == 303
        assert config.smtp_use_tls is False
    finally:
        app.dependency_overrides.clear()


def test_save_smtp_keeps_tls_when_checked():
    config = AppConfig(id=1, smtp_use_tls=False)
    db = _FakeDB({AppConfig: config})
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, follow_redirects=False)
        resp = client.post("/settings/smtp", data={
            "smtp_host": "smtp.example.de",
            "smtp_port": "587",
            "smtp_from": "a@b.de",
            "smtp_use_tls": "on",  # Checkbox angehakt
        })
        assert resp.status_code == 303
        assert config.smtp_use_tls is True
    finally:
        app.dependency_overrides.clear()


# ── save_smtp: kein stale Port bei leerem Host ──────────────────────────────

def test_save_smtp_empty_host_clears_port():
    """Wird der Host geleert, darf kein Port (Default 587) zurückbleiben,
    der später die .env-Konfiguration verdeckt."""
    config = AppConfig(id=1, smtp_host="alt.de", smtp_port=465)
    db = _FakeDB({AppConfig: config})
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, follow_redirects=False)
        resp = client.post("/settings/smtp", data={
            "smtp_host": "",          # Host geleert → DB-SMTP gilt als nicht konfiguriert
            "smtp_port": "587",
            "smtp_from": "",
        })
        assert resp.status_code == 303
        assert config.smtp_host is None
        assert config.smtp_port is None
    finally:
        app.dependency_overrides.clear()


# ── Settings-Seite: TLS-Checkbox spiegelt effektiven Wert ───────────────────

def test_settings_page_tls_checkbox_reflects_effective_value():
    """AppConfig-Zeile existiert, aber smtp_use_tls ist NULL → effektiver Wert ist der
    .env-Default (True). Die Checkbox muss dann 'checked' gerendert werden."""
    company = Company(id=1)
    config = AppConfig(id=1)  # alle SMTP-Felder NULL
    db = _FakeDB({Company: company, AppConfig: config})
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/settings/")
        assert resp.status_code == 200
        # Checkbox-Zeile für smtp_use_tls muss 'checked' enthalten
        html = resp.text
        idx = html.find('name="smtp_use_tls"')
        assert idx != -1
        # 'checked' steht im selben <input>-Tag (nach dem name-Attribut, vor dem schließenden >)
        tag_end = html.find(">", idx)
        assert "checked" in html[idx:tag_end]
    finally:
        app.dependency_overrides.clear()


# ── Settings-Seite: keine verschachtelten <form> (Testmail-Bug) ─────────────

def test_settings_page_has_no_nested_forms():
    """Verschachtelte <form> sind laut HTML-Spec verboten – der Browser verwirft
    das innere Formular. Lag das Testmail-Formular im SMTP-Speichern-Formular,
    postete 'TEST SENDEN' an /settings/smtp (speichern) statt /settings/smtp-test,
    sodass nie eine Testmail verschickt wurde."""
    from html.parser import HTMLParser

    class _FormNesting(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth = 0
            self.max_depth = 0

        def handle_starttag(self, tag, attrs):
            if tag == "form":
                self.depth += 1
                self.max_depth = max(self.max_depth, self.depth)

        def handle_endtag(self, tag):
            if tag == "form" and self.depth > 0:
                self.depth -= 1

    company = Company(id=1)
    config = AppConfig(id=1, smtp_host="smtp.gmail.com", smtp_port=587,
                       smtp_from="a@b.de")
    db = _FakeDB({Company: company, AppConfig: config})
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, follow_redirects=False)
        resp = client.get("/settings/")
        assert resp.status_code == 200
        parser = _FormNesting()
        parser.feed(resp.text)
        assert parser.max_depth <= 1, "verschachtelte <form> im Settings-Template"
        # Testmail-Button muss (auch bei gesetztem Host) an /settings/smtp-test posten
        assert "/settings/smtp-test" in resp.text
    finally:
        app.dependency_overrides.clear()


# ── SMTP-Passwort-Verschlüsselung (Fernet) ──────────────────────────────────

from app.services import crypto
from app.config import get_settings

_TEST_KEY = "test-secret-key-mit-mindestens-32-zeichen!!"


@pytest.fixture
def secret_key(monkeypatch):
    # crypto (ohne expliziten key) nutzt get_settings().secret_key
    monkeypatch.setattr(get_settings(), "secret_key", _TEST_KEY)
    return _TEST_KEY


def test_save_smtp_stores_password_encrypted(secret_key):
    config = AppConfig(id=1)
    db = _FakeDB({AppConfig: config})
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app, follow_redirects=False)
        resp = client.post("/settings/smtp", data={
            "smtp_host": "smtp.example.de",
            "smtp_port": "587",
            "smtp_from": "a@b.de",
            "smtp_password": "geheim123",
            "smtp_use_tls": "on",
        })
        assert resp.status_code == 303
        # In der DB liegt kein Klartext
        assert config.smtp_password != "geheim123"
        # aber es lässt sich wieder entschlüsseln
        assert crypto.decrypt(config.smtp_password) == "geheim123"
    finally:
        app.dependency_overrides.clear()


def test_effective_settings_decrypts_db_password(secret_key):
    db_cfg = SimpleNamespace(
        smtp_host="db-host.de", smtp_port=465, smtp_user="db-user",
        smtp_password=crypto.encrypt("geheim123"), smtp_from="db@from.de",
        smtp_use_tls=True, datev_bcc_email="db-datev@x.de",
    )
    eff = EffectiveSettings(db_cfg, _base())
    assert eff.smtp_password == "geheim123"


def test_effective_settings_password_falls_back_to_env(secret_key):
    db_cfg = SimpleNamespace(
        smtp_host="db-host.de", smtp_port=None, smtp_user=None,
        smtp_password=None, smtp_from=None, smtp_use_tls=None, datev_bcc_email=None,
    )
    eff = EffectiveSettings(db_cfg, _base(smtp_password="env-pw"))
    assert eff.smtp_password == "env-pw"
