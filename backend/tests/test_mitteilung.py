"""Mitteilung (#120, Nachtrag): eigene Zone, IMMER schliessbar, frei platzierbar.

Die Zone hiess frueher „Pro-Hinweis" und trug ein Abzeichen `PRO`. Beides stammte
aus einer Zeit, in der eine kostenpflichtige Ausbaustufe geplant war; die ist
verworfen. Ein Abzeichen, das eine Kaufversion ankuendigt, die es nicht geben wird,
gehoert nicht in ein veroeffentlichtes Programm — es heisst jetzt `INFO`.

Die Zone haengt bewusst NICHT am Update-Banner. Solange sie ein Feld von `Banner`
war, konnte sie nur dort erscheinen, wo auch ein Update-Banner steht, und nur in
dessen Layout. Jetzt hat sie eigenen Zustand (`compute_mitteilung`), einen eigenen
Endpunkt zum Schliessen und ein Makro mit Layout-Variante.

Geschlossen wird nach TEXT, nicht nach Version: eine Mitteilung hat keine Version.
Wer sie wegdrueckt, sieht genau diesen Text nie wieder; ein neuer Text darf wieder
erscheinen.
"""
from dataclasses import fields
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.services.update_banner import Banner, compute_mitteilung

JETZT = datetime.now(timezone.utc)

TEXT = "Es gibt jetzt eine begleitete Einrichtung."


def cfg(**kw):
    grund = dict(update_mitteilung_text=None, update_mitteilung_url=None,
                 update_mitteilung_verworfen=None)
    grund.update(kw)
    return SimpleNamespace(**grund)


# --- reine Anzeigelogik -------------------------------------------------


def test_ohne_text_keine_mitteilung():
    assert compute_mitteilung(cfg()) is None


def test_nur_leerzeichen_ist_kein_text():
    assert compute_mitteilung(cfg(update_mitteilung_text="   ")) is None


def test_text_wird_geliefert():
    m = compute_mitteilung(cfg(update_mitteilung_text=TEXT,
                               update_mitteilung_url="https://github.com/x"))
    assert m.text == TEXT
    assert m.url == "https://github.com/x"


def test_weggedrueckter_text_bleibt_weg():
    assert compute_mitteilung(cfg(update_mitteilung_text=TEXT,
                                  update_mitteilung_verworfen=TEXT)) is None


def test_neuer_text_kommt_wieder():
    m = compute_mitteilung(cfg(update_mitteilung_text="Etwas anderes.",
                               update_mitteilung_verworfen=TEXT))
    assert m is not None


def test_banner_traegt_den_mitteilungstext_nicht_mehr():
    """Strukturelle Trennung statt Disziplin: solange `Banner` die Felder trug,
    war „Mitteilung nie im nicht-schliessbaren Banner" eine reine
    Template-Vereinbarung. Ohne die Felder ist es nicht mehr moeglich."""
    namen = {f.name for f in fields(Banner)}
    assert not [n for n in namen if "mitteilung" in n or "pro" in n]


# --- Makro: gleiche Zone, anderes Layout --------------------------------


def _makro():
    return Jinja2Templates(directory="app/templates").env.get_template(
        "partials/mitteilung.html").module.mitteilung


def test_makro_rendert_die_gewuenschte_variante():
    from app.services.update_banner import Mitteilung
    html = str(_makro()(Mitteilung(TEXT, "https://github.com/x"),
                        variante="karte", weiter="/rechnungen"))
    assert 'data-mitteilung-variante="karte"' in html
    assert TEXT in html
    assert "data-mitteilung-schliessen" in html, \
        "ohne Schliessen-Knopf ist die Zone nicht schliessbar"
    assert 'value="/rechnungen"' in html, "der Nutzer muss auf seiner Seite bleiben"


def test_abzeichen_kuendigt_keine_kaufversion_an():
    from app.services.update_banner import Mitteilung
    html = str(_makro()(Mitteilung(TEXT)))
    assert "INFO" in html
    assert "PRO" not in html


def test_makro_ohne_mitteilung_rendert_nichts():
    assert str(_makro()(None)).strip() == ""


# --- Router / echtes Postgres -------------------------------------------


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _speichern(pg_session, **kw):
    c = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if c is None:
        c = AppConfig(id=1)
        pg_session.add(c)
    for k, v in kw.items():
        setattr(c, k, v)
    pg_session.commit()
    return c


def test_mitteilung_erscheint_auch_ohne_update_banner(client, pg_session):
    """Kein Update, frisch geprueft ⇒ kein Banner. Die Mitteilung muss trotzdem
    stehen — sonst haengt sie weiter am Banner und ist nicht frei platzierbar."""
    _speichern(pg_session, update_last_checked_at=JETZT, update_last_attempt_at=JETZT,
               update_latest_version=None, update_mitteilung_text=TEXT,
               update_mitteilung_url="https://github.com/x",
               update_mitteilung_verworfen=None)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "data-update-banner" not in r.text, "Vorbedingung: hier gibt es keinen Banner"
    assert TEXT in r.text
    assert "data-mitteilung-schliessen" in r.text


def test_schliessen_laesst_sie_verschwinden(client, pg_session):
    _speichern(pg_session, update_last_checked_at=JETZT, update_last_attempt_at=JETZT,
               update_mitteilung_text=TEXT, update_mitteilung_verworfen=None)
    r = client.post("/updates/mitteilung-schliessen", data={"weiter": "/dashboard"})
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"

    pg_session.expire_all()
    c = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert c.update_mitteilung_verworfen == TEXT

    assert TEXT not in client.get("/dashboard").text


def test_neuer_text_kommt_nach_dem_schliessen_wieder(client, pg_session):
    _speichern(pg_session, update_last_checked_at=JETZT, update_last_attempt_at=JETZT,
               update_mitteilung_text=TEXT, update_mitteilung_verworfen=TEXT)
    assert TEXT not in client.get("/dashboard").text

    _speichern(pg_session, update_mitteilung_text="Etwas ganz anderes.")
    assert "Etwas ganz anderes." in client.get("/dashboard").text


def test_fremdes_ziel_wird_verworfen(client, pg_session):
    """Sonst waere der Schliessen-Knopf eine offene Weiterleitung: ein Link auf
    /updates/mitteilung-schliessen?… koennte auf eine fremde Seite schicken."""
    _speichern(pg_session, update_mitteilung_text=TEXT, update_mitteilung_verworfen=None)
    for ziel in ["https://evil.com/x", "//evil.com", "/\\evil.com"]:
        r = client.post("/updates/mitteilung-schliessen", data={"weiter": ziel})
        assert r.headers["location"] == "/", f"{ziel} durfte nicht uebernommen werden"


def test_eskalierter_banner_bleibt_ohne_mitteilungstext(client, pg_session, monkeypatch):
    """Die alte Schutzregel muss die Umbenennung ueberleben."""
    monkeypatch.setattr("app.dependencies.update_banner_dep.get_settings",
                        lambda: SimpleNamespace(app_version="1.0.0"))
    _speichern(pg_session, update_latest_version="9.9.9", update_severity="security",
               update_notice="Sicherheitslücke.", update_mitteilung_text=TEXT,
               update_mitteilung_verworfen=None)
    r = client.get("/dashboard")
    banner = r.text.split('data-update-banner="escalated"')[1].split("</div>")[0]
    assert TEXT not in banner
    assert TEXT in r.text, "in eigener Zone erscheint sie sehr wohl"
