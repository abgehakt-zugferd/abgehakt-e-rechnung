"""
Der Zurück-Button darf kein abgeschicktes Anlegeformular zurückbringen.

Bug (2026-08-03, gemeldet für Rechnungsentwürfe): nach `POST …/neu` → 303 liegt der
History-Eintrag des Anlegeformulars direkt hinter der Zielseite. Der Browser stellt ihn
beim Zurück-Button samt eingetippter Werte wieder her (bfcache bzw.
Formular-Restoration) — das sieht aus wie ein Editor für den gerade gespeicherten
Datensatz, ist aber weiterhin das ANLEGE-Formular. Ein Absenden erzeugt einen ZWEITEN
Datensatz mit neuer laufender Nummer; bei Rechnungen ist der nach GoBD nie wieder
löschbar.

Die Regel gilt für jedes Anlegeformular, deshalb hier parametrisiert statt pro Router.
Zwei Ebenen, weil es zwei Wiederherstellungspfade gibt:

1. `Cache-Control: no-store` — wo der Browser neu lädt, kommt ein frisches, leeres
   Formular statt der gefüllten Kopie aus dem Cache.
2. Die Seite entwertet sich selbst, wenn sie als bereits abgeschickter History-Eintrag
   zurückkommt (`pageshow`/`persisted`/`back_forward`). Das ist der einzige Weg, der
   auch beim bfcache greift — dort wird der Server gar nicht erst gefragt.

Ebene 2 ist ein Markup-Regression-Guard (Vorbild `test_tempfile_safety.py`): das Repo
hat keinen JS-Testrunner. Beide Formulare sind ohnehin JS-abhängig (beim
Rechnungsformular ist `items_json` ein Alpine-Binding), eine JS-Leitplanke ist hier also
nicht schwächer als das Formular selbst.
"""
import uuid
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer


class Anlegeformular(NamedTuple):
    url: str
    key: str            # sessionStorage-Schlüssel der Abgeschickt-Markierung
    form_id: str
    hinweis_id: str
    hinweis_text: str


ANLEGEFORMULARE = [
    pytest.param(Anlegeformular(
        "/invoices/neu", "abgehakt:entwurf-formular-abgeschickt",
        "rechnung-anlegen", "rechnung-anlegen-verbraucht",
        "ENTWURF BEREITS GESPEICHERT"), id="rechnung"),
    pytest.param(Anlegeformular(
        "/customers/neu", "abgehakt:kunden-formular-abgeschickt",
        "kunde-anlegen", "kunde-anlegen-verbraucht",
        "KUNDE BEREITS ANGELEGT"), id="kunde"),
]


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    # Das Rechnungsformular braucht mindestens einen Kunden in der Auswahl.
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.commit()
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


@pytest.mark.parametrize("f", ANLEGEFORMULARE)
def test_anlegeformular_ist_nicht_cachebar(pg_session, f):
    """Kein Cache ⇒ der Zurück-Button holt ein frisches, leeres Formular vom Server."""
    r = _client(pg_session).get(f.url)
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", ""), (
        f"GET {f.url} ohne 'Cache-Control: no-store' — der Browser darf das ausgefüllte "
        "Formular nach dem Absenden aus dem Cache zurückgeben."
    )


@pytest.mark.parametrize("f", ANLEGEFORMULARE)
def test_anlegeformular_erkennt_zurueck_navigation(pg_session, f):
    """bfcache fragt den Server nicht — die Seite muss sich selbst entwerten."""
    html = _client(pg_session).get(f.url).text

    for marker in ("pageshow", "persisted", "back_forward"):
        assert marker in html, (
            f"'{marker}' fehlt in {f.url} — ohne Erkennung der Zurück-Navigation kommt "
            "das abgeschickte Formular gefüllt aus dem bfcache zurück."
        )
    assert f.key in html, (
        f"Markierung '{f.key}' fehlt in {f.url} — ohne sie ließe sich ein "
        "wiederhergestelltes Formular nicht von einem legitim offenen unterscheiden."
    )


@pytest.mark.parametrize("f", ANLEGEFORMULARE)
def test_anlegeformular_zeigt_hinweis_statt_editor(pg_session, f):
    """Entwertet heißt: Formular weg, Erklärung da — kein stiller Sprung."""
    html = _client(pg_session).get(f.url).text

    assert f'id="{f.form_id}"' in html, (
        f"Formular in {f.url} ohne id='{f.form_id}' — die Leitplanke findet es nicht "
        "und könnte es beim Zurückkommen nicht ausblenden."
    )
    assert f'id="{f.hinweis_id}"' in html and f.hinweis_text in html, (
        f"Kein Hinweis an der Stelle des Formulars in {f.url} — der Nutzer stünde ohne "
        "Erklärung vor einer leeren Seite."
    )


@pytest.mark.parametrize("f", ANLEGEFORMULARE)
def test_hinweis_ist_vor_dem_ersten_paint_unsichtbar(pg_session, f):
    """Ohne inline display:none blitzt der Hinweis bei jedem normalen Aufruf auf."""
    html = _client(pg_session).get(f.url).text
    block = html.split(f'id="{f.hinweis_id}"')[1][:400]
    assert "display:none" in block, (
        f"Hinweisblock in {f.url} ohne inline 'display:none' — er wäre beim normalen "
        "Anlegen kurz sichtbar, bis das Skript ihn versteckt."
    )
