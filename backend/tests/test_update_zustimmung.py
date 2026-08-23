"""
Zustimmungsseite und Update-Hinweis (#120): was dort steht, muss stimmen, und
was man anklicken soll, muss wie ein Knopf aussehen.

Drei Befunde vom 2026-08-11, alle in derselben Ecke:

1. Die Zustimmungsseite zeigte `…/releases/latest?version=1.0.0&edition=free`
   und nannte das „übertragen wird ausschließlich das Folgende".
   `update_check.fetch_update_info` ruft aber `ENDPOINT` OHNE Anhang auf — der
   Quelltext dort hält ausdrücklich fest, dass Version und Ausgabe nicht
   übertragen werden, und das README sagt dasselbe. Die Seite zeigte also eine
   Adresse, die es nicht gibt, und ließ sich genau die beiden Angaben
   bestätigen, die als einzige NICHT hinausgehen. Eine Einwilligung, die etwas
   Falsches beschreibt, ist keine.

2. Knöpfe und Verweise trugen keine Klasse. In einer Oberfläche, deren
   Bedienelemente ihre Form ausschließlich aus `.btn-*` beziehen, rendert das
   als Fließtext: „Einverstanden, jetzt prüfen" und „Abbrechen" standen
   untereinander wie zwei Sätze.

3. Der Hinweis meldete ein Update, sagte aber nicht, wie man es einspielt —
   `/updates/anleitung` war von keiner Seite aus verlinkt.

Geprüft wird gegen den Inhaltsbereich, nicht gegen die ganze Seite: das
Grundgerüst bringt eigene Schaltflächen mit (Seitenleiste, Themenwechsel), die
bewusst anders aussehen.
"""
import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.services import update_check

JETZT = datetime.now(timezone.utc)

# Jedes öffnende <button …> mitsamt seinen Attributen.
KNOPF = re.compile(r"<button\b[^>]*>", re.IGNORECASE)


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _version_festnageln(monkeypatch, version="1.0.0"):
    """Im Entwicklungscontainer ist APP_VERSION='dev', und eine dev-Version wird
    nie verglichen — ohne dieses Festnageln bliebe der Hinweis unsichtbar und
    jeder Render-Test hier wäre grün, ohne etwas zu prüfen."""
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


def _zustimmungsseite(client, pg_session, monkeypatch) -> str:
    _cfg(pg_session, update_consent_at=None)
    # Ein Aufruf wäre hier ein Fehler: ohne Bestätigung geht nichts hinaus.
    monkeypatch.setattr("app.routers.updates.fetch_update_info",
                        lambda *a, **k: pytest.fail("vor der Bestätigung darf nichts abgerufen werden"))
    r = client.post("/updates/pruefen")
    assert r.status_code == 200
    assert 'data-seite="update-zustimmung"' in r.text
    return r.text.split('data-seite="update-zustimmung"')[1]


def _hinweis(client, art="normal") -> str:
    """Der Hinweis-Kasten, abgeschnitten am ersten </div> — deshalb enthält er
    bewusst keine verschachtelten Kästen."""
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert f'data-update-banner="{art}"' in r.text
    return r.text.split(f'data-update-banner="{art}"')[1].split("</div>")[0]


# --- 1. Die Seite muss die Wahrheit sagen ---------------------------------

def test_zustimmung_zeigt_die_adresse_die_wirklich_gerufen_wird(client, pg_session, monkeypatch):
    inhalt = _zustimmungsseite(client, pg_session, monkeypatch)

    assert update_check.ENDPOINT in inhalt
    assert "?version=" not in inhalt, (
        "Die Seite zeigt einen Abfrageteil, den fetch_update_info nie anhängt."
    )
    assert "edition=" not in inhalt


def test_zustimmung_behauptet_nicht_die_version_werde_uebertragen(client, pg_session, monkeypatch):
    """Der Kern des Befundes: bestätigt wurde die Übertragung von genau dem,
    was als einziges nicht hinausgeht."""
    inhalt = _zustimmungsseite(client, pg_session, monkeypatch)

    assert "nichts" in inhalt.lower(), (
        "Die Seite muss sagen, dass über diese Installation nichts mitgeht."
    )


def test_zustimmung_benennt_was_der_gegenueber_trotzdem_sieht(client, pg_session, monkeypatch):
    """Nichts zu senden heißt nicht, unsichtbar zu sein. Wer eine Adresse
    aufruft, zeigt seine IP-Adresse — das gehört in die Einwilligung, sonst ist
    sie geschönt."""
    inhalt = _zustimmungsseite(client, pg_session, monkeypatch)

    assert "IP-Adresse" in inhalt


# --- 2. Bedienelemente müssen wie Bedienelemente aussehen ------------------

def test_knoepfe_der_zustimmung_sind_als_knopf_erkennbar(client, pg_session, monkeypatch):
    inhalt = _zustimmungsseite(client, pg_session, monkeypatch)

    knoepfe = KNOPF.findall(inhalt)
    assert knoepfe, "Vorbedingung: die Seite hat einen Knopf"
    for k in knoepfe:
        assert "btn-" in k, f"Knopf ohne Form, rendert als Text: {k}"


def test_abbrechen_ist_kein_nackter_verweis(client, pg_session, monkeypatch):
    """`Abbrechen` steht neben dem Bestätigen-Knopf und muss dieselbe Form haben
    — als blanker Verweis war es von einem Absatz nicht zu unterscheiden."""
    inhalt = _zustimmungsseite(client, pg_session, monkeypatch)

    abbrechen = inhalt.split("Abbrechen")[0].rsplit("<a", 1)[-1]
    assert "btn-" in abbrechen


def test_knoepfe_im_hinweis_sind_als_knopf_erkennbar(client, pg_session, monkeypatch):
    _version_festnageln(monkeypatch)
    _cfg(pg_session, update_consent_at=JETZT, update_latest_version="9.9.9",
         update_severity="normal", update_notice="Version 9.9.9 ist verfügbar.")

    for k in KNOPF.findall(_hinweis(client)):
        assert "btn-" in k, f"Knopf ohne Form, rendert als Text: {k}"


# --- 3. Der Hinweis muss den Weg zeigen -----------------------------------

def test_hinweis_auf_ein_update_verweist_auf_die_anleitung(client, pg_session, monkeypatch):
    """Ein Hinweis, der ein Update meldet, aber nicht sagt, wie es hineinkommt,
    lässt den Nutzer allein. Die Anleitung gab es, nur führte kein Weg dorthin."""
    _version_festnageln(monkeypatch)
    _cfg(pg_session, update_consent_at=JETZT, update_latest_version="9.9.9",
         update_severity="normal", update_notice="Version 9.9.9 ist verfügbar.")

    assert "/updates/anleitung" in _hinweis(client)


def test_blosse_erinnerung_verweist_nicht_auf_die_anleitung(client, pg_session, monkeypatch):
    """Gegenprobe, damit der Verweis etwas bedeutet: Wer seit Langem nicht
    gesucht hat, hat kein Update vor sich, das er einspielen könnte."""
    _version_festnageln(monkeypatch)
    _cfg(pg_session, update_consent_at=JETZT, update_latest_version=None,
         update_last_checked_at=None, update_last_attempt_at=None,
         update_snoozed_until=None)

    assert "/updates/anleitung" not in _hinweis(client, art="reminder")
