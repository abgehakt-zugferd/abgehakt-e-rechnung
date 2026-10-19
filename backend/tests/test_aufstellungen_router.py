"""Router /aufstellungen: Stellen und PDF-Abruf (§ 8b, Bauschritt 7c).

Liste und Detailseiten kommen mit 7g — jetzt gibt es nur den Handgriff,
der den Entwurf stellt, und den Weg zum archivierten PDF. Fehler sind 400
mit Meldung, damit der Mensch weiss, warum nichts gestellt wurde.
"""
import uuid
from datetime import datetime, timezone

import pytest

import app.zeit
from app.config import get_settings
from app.models.aufstellung import Aufstellung
from app.services import pdfa
from tests.factories_aufstellung import speichere_aufstellung


@pytest.fixture(autouse=True)
def heutiger_tag(monkeypatch):
    monkeypatch.setattr(
        app.zeit, "_utc_jetzt",
        lambda: datetime(2026, 10, 18, 3, 30, tzinfo=timezone.utc),
    )


@pytest.mark.skipif(not pdfa.gs_available(), reason="Ghostscript nicht verfügbar")
def test_finalisieren_route_stellt_die_aufstellung(client, pg_session):
    a = speichere_aufstellung(pg_session)

    antwort = client.post(f"/aufstellungen/{a.id}/finalisieren")

    assert antwort.status_code == 303
    assert antwort.headers["location"] == f"/aufstellungen/{a.id}"
    pg_session.expire_all()
    frisch = pg_session.query(Aufstellung).one()
    assert frisch.status == "issued"
    assert (get_settings().storage_path / "aufstellungen" / f"{a.nummer}.pdf").exists()


@pytest.mark.skipif(not pdfa.gs_available(), reason="Ghostscript nicht verfügbar")
def test_zweites_finalisieren_ueber_die_route_ist_400(client, pg_session):
    a = speichere_aufstellung(pg_session)
    client.post(f"/aufstellungen/{a.id}/finalisieren")

    antwort = client.post(f"/aufstellungen/{a.id}/finalisieren")

    # Abgewiesene Anfragen kommen als Fehlerseite (main.py: fehlerseite),
    # nicht als JSON — die Meldung steht im Text.
    assert antwort.status_code == 400
    assert "Entwurf" in antwort.text


def test_verworfene_aufstellung_wird_nicht_gestellt(client, pg_session):
    a = speichere_aufstellung(pg_session, status="discarded")

    antwort = client.post(f"/aufstellungen/{a.id}/finalisieren")

    assert antwort.status_code == 400
    assert "discarded" in antwort.text


def test_unbekannte_aufstellung_ist_404(client):
    assert client.post(f"/aufstellungen/{uuid.uuid4()}/finalisieren").status_code == 404
    assert client.get(f"/aufstellungen/{uuid.uuid4()}/pdf").status_code == 404


@pytest.mark.skipif(not pdfa.gs_available(), reason="Ghostscript nicht verfügbar")
def test_pdf_route_liefert_das_archivierte_pdf(client, pg_session):
    a = speichere_aufstellung(pg_session)
    client.post(f"/aufstellungen/{a.id}/finalisieren")

    antwort = client.get(f"/aufstellungen/{a.id}/pdf")

    assert antwort.status_code == 200
    assert antwort.headers["content-type"].startswith("application/pdf")
    pfad = get_settings().storage_path / "aufstellungen" / f"{a.nummer}.pdf"
    assert antwort.content == pfad.read_bytes()
    assert a.nummer in antwort.headers["content-disposition"]


def test_pdf_eines_entwurfs_ist_404(client, pg_session):
    """Nur die GESTELLTE Aufstellung hat ein PDF im Archiv (§ 8b):
    ein Entwurf ist kein Beleg und hat nichts zu liefern."""
    a = speichere_aufstellung(pg_session)

    assert client.get(f"/aufstellungen/{a.id}/pdf").status_code == 404
