"""Gesundheitsroute GET /gesundheit fuer den Healthcheck und einen Proxy.

Sie gibt keine Daten aus: nur `{"status": "ok"}` (200), wenn ein `SELECT 1` gelingt,
sonst `{"status": "db_nicht_erreichbar"}` (503) ohne Fehlertext. Sie braucht keine
Anmeldung (die Anwendung hat keine) und wird vom Einrichtungstor nicht umgeleitet.
Die Datenbank ist die Systemgrenze: die gestoerte Sitzung ist die einzige Attrappe.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.database import get_db
from app.main import app
from tests.helpers.firma_eingerichtet import leere_firma

GEHEIMER_FEHLERTEXT = "connection to server at db-intern-7 refused, passwort=geheim"


class _GestoerteSitzung:
    """Eine Datenbank, die nicht antwortet: jede Abfrage scheitert mit Fehlertext."""

    def _fehler(self, *_a, **_k):
        raise OperationalError("SELECT 1", {}, Exception(GEHEIMER_FEHLERTEXT))

    execute = query = scalar = connection = _fehler

    def rollback(self):
        self._fehler()

    def close(self):
        pass


@pytest.fixture()
def client_db_gestoert(pg_session):
    app.dependency_overrides[get_db] = lambda: _GestoerteSitzung()
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_gesunde_db_liefert_200_und_nur_status_ok(client):
    antwort = client.get("/gesundheit")

    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok"}


def test_gestoerte_db_liefert_503_ohne_fehlertext(client_db_gestoert):
    antwort = client_db_gestoert.get("/gesundheit")

    assert antwort.status_code == 503
    assert antwort.json() == {"status": "db_nicht_erreichbar"}
    for geheim in ("db-intern-7", "passwort", "OperationalError", "SELECT"):
        assert geheim not in antwort.text


def test_ohne_einrichtung_keine_umleitung_auf_setup(client, pg_session):
    leere_firma(pg_session)

    antwort = client.get("/gesundheit")

    assert antwort.status_code == 200
    assert antwort.json() == {"status": "ok"}


def test_antwort_enthaelt_keine_firmen_oder_rechnungsdaten(client):
    """Die Fixture-Firma ist eingerichtet; ihr Name, Ort und ihre Nummern duerfen
    nirgends in der Antwort stehen, auch nicht in Kopfzeilen."""
    antwort = client.get("/gesundheit")

    sichtbar = antwort.text + str(dict(antwort.headers))
    for datum in ("Muster Handwerk", "Musterstadt", "12/345/67890", "DE123456789", "RE-"):
        assert datum not in sichtbar
    assert antwort.headers["content-type"].startswith("application/json")


def test_gesundheit_ist_eine_lesende_route(client):
    assert client.post("/gesundheit").status_code == 405



def test_ausnahme_gilt_nur_fuer_den_exakten_pfad():
    """Die Ausnahme im Einrichtungstor ist kein Praefix: ein Pfad unter /gesundheit
    waere keine Gesundheitsroute und bekaeme sonst still das Tor erlassen. (Ein
    HTTP-Test geht hier nicht: ohne passende Route laeuft keine Abhaengigkeit, die
    Antwort waere ohnehin 404. Deshalb die Entscheidung des Tors selbst.)"""
    from app.dependencies.einrichtungstor import pfad_ausgenommen

    assert pfad_ausgenommen("/gesundheit") is True
    for pfad in ("/gesundheit/x", "/gesundheit/", "/gesundheitx", "/gesundheit/db"):
        assert pfad_ausgenommen(pfad) is False, pfad
    # Die Praefix-Ausnahmen bleiben Praefixe.
    assert pfad_ausgenommen("/settings/firma") is True
