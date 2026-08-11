"""Ein fehlgeschlagener Update-Hinweis darf nicht die ganze Seite mitreissen (#150).

`load_update_banner` haengt app-weit und faengt bewusst jede Ausnahme: ein kaputter
Hinweis darf die Anwendung nicht unbenutzbar machen. Nur genuegt das Abfangen allein
nicht. Schlaegt die Abfrage in Postgres fehl, ist die **Transaktion** abgebrochen, und
weil die naechste Route dieselbe Sitzung weiterbenutzt, stirbt danach jede weitere
Abfrage mit `InFailedSqlTransaction`.

Das Schadensbild ist nicht der eine Fehler, sondern seine Verdeckung: der echte Grund
steht nirgends, sichtbar sind nur sieben Folgefehler und ein 500 auf jeder Seite. Genau
so ist es bei der Kern-Extraktion passiert (fehlende Spalte, die das Modell noch
deklarierte) und die Suche dauerte laenger als der Fehler wert war.

Deshalb zwei Pflichten im `except`-Zweig:

* **`db.rollback()`** — sonst ist das Abfangen nur eine Verzoegerung des Absturzes.
* **eine Logzeile** — ein spurlos verschluckter Fehler ist schlimmer als ein lauter.

Der Test faelscht den Fehler nicht mit einem Mock, sondern loest ihn in Postgres
wirklich aus (Abfrage auf eine Tabelle, die es nicht gibt). Nur so ist die Transaktion
echt abgebrochen — ein `raise` aus einem Mock heraus wuerde gruen bleiben, auch ohne
Rollback.
"""
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer
from sqlalchemy.orm import declarative_base

from app.database import get_db
from app.dependencies import update_banner_dep
from app.main import app

_Base = declarative_base()


class _Gespenst(_Base):
    """Ein Modell ohne Tabelle. `db.query(...)` darauf laeuft bis nach Postgres
    durch und scheitert dort — anders als ein Mock, der schon vorher wirft und die
    Transaktion unberuehrt liesse."""
    __tablename__ = "tabelle_die_es_nicht_gibt"
    id = Column(Integer, primary_key=True)


def teardown_function():
    app.dependency_overrides.clear()


@pytest.fixture()
def client_mit_kaputtem_hinweis(pg_session, monkeypatch):
    monkeypatch.setattr(update_banner_dep, "AppConfig", _Gespenst)
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False, raise_server_exceptions=False)


def test_die_seite_bleibt_benutzbar(client_mit_kaputtem_hinweis):
    """Ohne Rollback antwortet hier 500 — nicht wegen des Hinweises, sondern weil
    die Rechnungsliste in der abgebrochenen Transaktion nicht mehr abfragen kann."""
    antwort = client_mit_kaputtem_hinweis.get("/invoices/")

    assert antwort.status_code == 200, "Der kaputte Hinweis reisst die Seite mit"


def test_auch_die_naechste_anfrage_geht_noch(client_mit_kaputtem_hinweis):
    """Die Sitzung ueberlebt den Fehler, nicht nur die eine Anfrage. Genau das
    unterscheidet ein Rollback von einer neuen Sitzung je Aufruf."""
    client_mit_kaputtem_hinweis.get("/invoices/")

    antwort = client_mit_kaputtem_hinweis.get("/customers/")

    assert antwort.status_code == 200, "Die Sitzung bleibt abgebrochen zurueck"


def test_der_fehler_steht_im_log(client_mit_kaputtem_hinweis, caplog):
    """Fuer den Nutzer still, fuer den Betreiber nicht: sonst sucht beim naechsten
    Mal wieder jemand stundenlang nach einer Ursache, die niemand aufgeschrieben hat."""
    with caplog.at_level(logging.ERROR):
        client_mit_kaputtem_hinweis.get("/invoices/")

    meldungen = [e for e in caplog.records if e.levelno >= logging.ERROR]
    assert meldungen, "Der Fehler wurde spurlos verschluckt"
    assert any("tabelle_die_es_nicht_gibt" in e.getMessage() + str(e.exc_info or "")
               for e in meldungen), "Die Logzeile nennt die Ursache nicht"
