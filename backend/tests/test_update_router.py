"""Router + Banner (#120) gegen echtes Postgres.

Der wichtigste Test hier ist test_eskalierter_banner_steht_im_html: Ein fehlendes
request.state-Attribut rendert in Jinja STUMM als Undefined — der Banner wuerde
also lautlos ausfallen, ohne dass ein Logiktest davon etwas merkt.

Gerendert wird gegen /dashboard, NICHT gegen /: `/` ist selbst eine Weiterleitung,
und die Fixture folgt bewusst keinen Weiterleitungen (sonst landet der Client in
falschem Zustand). Ein `get("/")` liefert hier also nie eine Seite.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.services import update_check

JETZT = datetime.now(timezone.utc)


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _version_festnageln(monkeypatch, version="1.0.0"):
    """Im Entwicklungscontainer ist APP_VERSION='dev' — und eine dev-Version wird
    laut Spec §4.6 NIE verglichen, der Banner bliebe also immer unsichtbar. Ein
    Render-Test ohne dieses Festnageln prueft nichts und waere gruen, sobald man
    ihn auf 'kein Banner' umschreibt. Gepatcht wird der Name in der Abhaengigkeit,
    nicht in app.config: get_settings ist zwischengespeichert (lru_cache)."""
    from types import SimpleNamespace
    monkeypatch.setattr("app.dependencies.update_banner_dep.get_settings",
                        lambda: SimpleNamespace(app_version=version))


def _cfg(pg_session, **kw):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    for k, v in kw.items():
        setattr(cfg, k, v)
    pg_session.commit()
    return cfg


def test_erster_klick_fuehrt_zur_offenlegung_und_sendet_nichts(client, pg_session, monkeypatch):
    _cfg(pg_session, update_consent_at=None)
    gerufen = []
    # WICHTIG: den Namen im Router patchen, nicht im Service. `updates.py` holt
    # die Funktion per `from ... import` — ein Patch am Service-Modul ginge ins
    # Leere und der Test waere falsch-gruen.
    monkeypatch.setattr("app.routers.updates.fetch_update_info",
                        lambda *a, **k: gerufen.append(1))

    r = client.post("/updates/pruefen")
    assert r.status_code == 200
    assert "version" in r.text.lower()
    assert gerufen == [], "ohne Bestätigung darf NICHTS übertragen werden"


def test_erfolgreiche_pruefung_schreibt_beide_zeitstempel(client, pg_session, monkeypatch):
    _cfg(pg_session, update_consent_at=JETZT)
    monkeypatch.setattr(
        "app.routers.updates.fetch_update_info",
        lambda *a, **k: update_check.UpdateInfo(
            latest_version="9.9.9", severity="security", notice="Wichtig.",
            url="https://abgehakt.app/changelog"),
    )
    r = client.post("/updates/pruefen", data={"bestaetigt": "1"})
    assert r.status_code == 303

    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.update_last_checked_at is not None
    assert cfg.update_last_attempt_at is not None
    assert cfg.update_latest_version == "9.9.9"


def test_fehlgeschlagene_pruefung_setzt_nur_den_versuch(client, pg_session, monkeypatch):
    frueher = JETZT - timedelta(days=60)
    _cfg(pg_session, update_consent_at=JETZT, update_last_checked_at=frueher,
         update_latest_version="1.0.0")

    def kaputt(*a, **k):
        raise update_check.UpdateCheckError("kein Netz")

    monkeypatch.setattr("app.routers.updates.fetch_update_info", kaputt)
    r = client.post("/updates/pruefen", data={"bestaetigt": "1"})
    assert r.status_code == 303

    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.update_last_attempt_at > cfg.update_last_checked_at
    assert cfg.update_latest_version == "1.0.0", "gespeicherte Daten bleiben unberührt"


def test_schliessen_setzt_dismissed_version(client, pg_session):
    _cfg(pg_session, update_consent_at=JETZT, update_latest_version="9.9.9",
         update_severity="normal")
    r = client.post("/updates/hinweis-schliessen")
    assert r.status_code == 303
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.update_dismissed_version == "9.9.9"


def test_eskalierter_banner_steht_im_html(client, pg_session, monkeypatch):
    _version_festnageln(monkeypatch)
    _cfg(pg_session, update_consent_at=JETZT, update_latest_version="9.9.9",
         update_severity="legal", update_notice="Setzt die Sendepflicht um.",
         update_mitteilung_text=None, update_mitteilung_url=None)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "Setzt die Sendepflicht um." in r.text
    assert 'data-update-banner="escalated"' in r.text
    assert 'data-update-dismiss' not in r.text, "eskaliert ist nicht schließbar"


def test_pro_block_niemals_im_eskalierten_banner(client, pg_session, monkeypatch):
    _version_festnageln(monkeypatch)
    _cfg(pg_session, update_consent_at=JETZT, update_latest_version="9.9.9",
         update_severity="security", update_notice="Sicherheitslücke.",
         update_mitteilung_text="Pro empfängt E-Rechnungen.",
         update_mitteilung_url="https://abgehakt.app/shop")
    r = client.get("/dashboard")
    assert 'data-update-banner="escalated"' in r.text
    eskaliert = r.text.split('data-update-banner="escalated"')[1].split("</div>")[0]
    assert "Pro empfängt" not in eskaliert
    assert 'data-mitteilung' in r.text, "der Pro-Block erscheint, aber in eigener Zone"


def test_fehler_in_der_abhaengigkeit_legt_die_seite_nicht_lahm(client, pg_session, monkeypatch):
    """Wirft die App-weite Abhaengigkeit, antworten sonst ALLE Routen mit 500 —
    genau der Fall beim Update, wenn Code auf noch nicht migrierte Spalten trifft."""
    def kaputt(*a, **k):
        raise RuntimeError("Spalte fehlt")

    monkeypatch.setattr("app.dependencies.update_banner_dep.compute_banner", kaputt)
    r = client.get("/dashboard")
    assert r.status_code == 200


def test_404_bleibt_404(client):
    assert client.get("/gibt-es-nicht").status_code == 404
