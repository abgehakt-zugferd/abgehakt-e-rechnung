"""Einrichtungstor auf belegerzeugende Seiten (#218).

Ohne abgeschlossene Ersteinrichtung leitet nur `/dashboard` um. Andere
belegerzeugende Pfade bleiben offen. Gewuenscht: ein Tor an einer Stelle,
`ist_eingerichtet` als einzige Definition, HTML und Formular-POST als 303
auf `/setup`.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.company import Company
from tests.helpers.firma_eingerichtet import leere_firma


def _eingerichtet(pg_session):
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    firma.setup_completed_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    pg_session.commit()


# --- geschuetzt: Umleitung ohne Einrichtung ---

@pytest.mark.parametrize("pfad", [
    "/dashboard",
    "/invoices/",
    "/uebergaben",
    "/aufstellungen",
    "/customers/",
])
def test_geschuetzter_bereich_leitet_ohne_einrichtung_auf_setup_um(
    client, pg_session, pfad,
):
    leere_firma(pg_session)

    antwort = client.get(pfad)

    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/setup"


def test_formular_post_leitet_ohne_einrichtung_auf_setup_um_statt_500(
    client, pg_session,
):
    leere_firma(pg_session)

    antwort = client.post("/invoices/neu", data={})

    assert antwort.status_code == 303
    assert antwort.headers["location"] == "/setup"


# --- geschuetzt: Durchlass mit Einrichtung ---

@pytest.mark.parametrize("pfad", [
    "/dashboard",
    "/invoices/",
    "/uebergaben",
    "/aufstellungen",
    "/customers/",
])
def test_geschuetzter_bereich_bleibt_mit_einrichtung_erreichbar(
    client, pg_session, pfad,
):
    """Durchlass: keine Umleitung auf /setup. 404 bei /uebergaben ohne Schalter
    ist erlaubt — das Tor hat die Anfrage durchgelassen."""
    _eingerichtet(pg_session)

    antwort = client.get(pfad)

    assert not (
        antwort.status_code == 303 and antwort.headers.get("location") == "/setup"
    )


# --- ausgenommen: ohne Einrichtung erreichbar ---

@pytest.mark.parametrize("pfad", [
    "/setup",
    "/settings/",
    "/archiv",
    "/export/",
    "/updates/anleitung",
    "/",
])
def test_ausgenommener_bereich_ist_ohne_einrichtung_erreichbar(
    client, pg_session, pfad,
):
    leere_firma(pg_session)

    antwort = client.get(pfad)

    # `/` antwortet mit 307 auf `/dashboard`; andere Ausnahmen mit 200.
    assert antwort.status_code in (200, 303, 307)
    if antwort.status_code in (303, 307):
        assert antwort.headers["location"] != "/setup"
