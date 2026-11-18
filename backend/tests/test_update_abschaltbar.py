"""Update-Pruefung per Umgebung abschaltbar: `UPDATE_PRUEFUNG=aus`.

Hinter einem Proxy ohne Weg nach aussen soll die Anwendung api.github.com nie
anfragen. Ist die Pruefung aus, gibt es keinen Knopf, keine Erinnerung an eine
Pruefung, und `POST /updates/pruefen` antwortet mit 403 ohne Netzabruf: die Anfrage
ist verstanden, der Betreiber hat die Funktion untersagt, und das aendert sich nicht
von selbst (anders als bei 503), die Seite ist auch nicht unbekannt (anders als 404).

Die Netzgrenze ist die einzige Attrappe: `httpx.Client` zaehlt Aufrufe mit.
"""
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig

JETZT = datetime.now(timezone.utc)


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def umgebung(monkeypatch):
    """Setzt die Umgebung und leert den Settings-Cache davor und danach."""
    def setzen(**werte):
        for name, wert in werte.items():
            monkeypatch.setenv(name, wert)
        get_settings.cache_clear()
    yield setzen
    monkeypatch.undo()
    get_settings.cache_clear()


@pytest.fixture
def netz(monkeypatch):
    """Die Netzgrenze: jeder Versuch, einen httpx.Client zu bauen, wird gezaehlt
    und scheitert wie ein fehlender Weg nach aussen."""
    aufrufe = []

    class _KeinNetz:
        def __init__(self, *a, **k):
            aufrufe.append(1)
            raise httpx.ConnectError("kein Netz")

    monkeypatch.setattr(httpx, "Client", _KeinNetz)
    return aufrufe


def _cfg(pg_session, **kw):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    for k, v in kw.items():
        setattr(cfg, k, v)
    pg_session.commit()


# --- die Einstellung ---

def test_vorgabe_ist_an():
    """Ungesetzt und leer (`UPDATE_PRUEFUNG=`) gelten als `an`."""
    assert Settings(secret_key="x" * 32, update_pruefung="").update_pruefung_aktiv is True
    assert Settings(secret_key="x" * 32).update_pruefung_aktiv is True


@pytest.mark.parametrize("wert", ["an", "An", " AN ", "  "])
def test_an_in_jeder_schreibweise_ist_aktiv(wert):
    """Gross- und Kleinschreibung und Leerzeichen am Rand sind egal; nur Leerzeichen = leer."""
    assert Settings(secret_key="x" * 32, update_pruefung=wert).update_pruefung_aktiv is True


@pytest.mark.parametrize("wert", ["aus", "AUS", " aus "])
def test_aus_schaltet_ab(wert):
    assert Settings(secret_key="x" * 32, update_pruefung=wert).update_pruefung_aktiv is False


@pytest.mark.parametrize("wert", ["nein", "off", "false", "0", "aus."])
def test_unbekannter_wert_bricht_laut_ab(wert):
    """Ein Tippfehler darf die Pruefung nicht still eingeschaltet lassen."""
    with pytest.raises(ValueError, match="UPDATE_PRUEFUNG"):
        Settings(secret_key="x" * 32, update_pruefung=wert)


# --- die Route ---

def test_aus_pruefen_antwortet_403_abgeschaltet_ohne_netzabruf(
    client, pg_session, umgebung, netz,
):
    _cfg(pg_session, update_consent_at=JETZT)
    umgebung(UPDATE_PRUEFUNG="aus")

    r = client.post("/updates/pruefen", data={"bestaetigt": "1"})

    assert r.status_code == 403
    assert "abgeschaltet" in r.text
    assert netz == [], "bei aus darf kein httpx-Aufruf stattfinden"


def test_aus_wirkt_auch_vor_der_einwilligung(client, pg_session, umgebung, netz):
    _cfg(pg_session, update_consent_at=None)
    umgebung(UPDATE_PRUEFUNG="aus")

    r = client.post("/updates/pruefen")

    assert r.status_code == 403
    assert "abgeschaltet" in r.text
    assert netz == []


def test_an_pruefen_ruft_das_netz_kontrolle(client, pg_session, umgebung, netz):
    """Gegenprobe: ohne `aus` erreicht die Anfrage die Netzgrenze, die Attrappe taugt."""
    _cfg(pg_session, update_consent_at=JETZT)
    umgebung(UPDATE_PRUEFUNG="an")

    r = client.post("/updates/pruefen", data={"bestaetigt": "1"})

    assert r.status_code == 303
    assert netz == [1]


# --- der Knopf ---

def _erinnerung_stellen(pg_session):
    """Nie gesucht und Version nicht 'dev': der Erinnerungs-Banner mit Knopf erscheint."""
    _cfg(pg_session, update_last_checked_at=None, update_last_attempt_at=None,
         update_latest_version=None, update_snoozed_until=None)


def test_an_zeigt_den_knopf_kontrolle(client, pg_session, umgebung):
    _erinnerung_stellen(pg_session)
    umgebung(APP_VERSION="1.0.0", UPDATE_PRUEFUNG="an")

    html = client.get("/dashboard").text

    assert "Jetzt suchen" in html
    assert 'action="/updates/pruefen"' in html


def test_aus_zeigt_keinen_knopf(client, pg_session, umgebung):
    _erinnerung_stellen(pg_session)
    umgebung(APP_VERSION="1.0.0", UPDATE_PRUEFUNG="aus")

    html = client.get("/dashboard").text

    assert "Jetzt suchen" not in html
    assert "/updates/pruefen" not in html
    assert "nach Updates gesucht" not in html
