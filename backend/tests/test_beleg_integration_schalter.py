"""Der Schalter der Beleg-Integration (abgehakt#22, Punkte 1 und 2).

Voreinstellung AUS. Solange er aus ist, existiert weder das Menue noch die
Schnittstellen-ID noch die Protokollfassung. Das ist keine Bequemlichkeit:
abgehakt ist die einzige der beteiligten Anwendungen, die ausgeliefert wird -
oeffentliches Repositorium, Installationsanleitung, fremde Rechner. Ein Menue
fuer eine Kette, von der ein fremder Installateur nie gehoert hat, ist dort
Verwirrung.

Die Kehrseite gehoert in die Anleitung: wer die Kette einrichtet, muss die
Integration ZUERST einschalten, sonst findet er die Kennung nicht, die die
Gegenseite von ihm verlangt.
"""

import uuid

import pytest

from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.services.protokoll import PROTOKOLL_VERSION


def _schalter(pg_session, aktiv: bool) -> AppConfig:
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.beleg_integration_aktiv = aktiv
    pg_session.commit()
    return cfg


def _kunde(pg_session) -> Customer:
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autorin A",
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
    )
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def test_die_voreinstellung_ist_aus(pg_session):
    pg_session.add(AppConfig(id=1))
    pg_session.commit()

    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.beleg_integration_aktiv is False


def test_die_einstellungen_zeigen_den_schalter(client):
    antwort = client.get("/settings/")

    assert antwort.status_code == 200
    assert "BELEG-INTEGRATION" in antwort.text.upper()


def test_der_schalter_laesst_sich_einschalten(client, pg_session):
    antwort = client.post("/settings/beleg-integration", data={"aktiv": "1"})

    assert antwort.status_code == 303
    pg_session.expire_all()
    assert pg_session.query(AppConfig).filter(AppConfig.id == 1).first().beleg_integration_aktiv


def test_der_schalter_laesst_sich_wieder_ausschalten(client, pg_session):
    _schalter(pg_session, True)

    client.post("/settings/beleg-integration", data={})

    pg_session.expire_all()
    assert not pg_session.query(AppConfig).filter(AppConfig.id == 1).first().beleg_integration_aktiv


def test_ohne_schalter_keine_protokollfassung(client, pg_session):
    _schalter(pg_session, False)

    text = client.get("/settings/").text

    assert "Programmfassung" in text
    assert "Protokollfassung" not in text


def test_mit_schalter_stehen_beide_fassungen_nebeneinander(client, pg_session):
    _schalter(pg_session, True)

    text = client.get("/settings/").text

    assert "Programmfassung" in text
    assert "Protokollfassung" in text
    assert PROTOKOLL_VERSION in text


def test_ohne_schalter_keine_schnittstellen_id_im_kundenformular(client, pg_session):
    kunde = _kunde(pg_session)
    _schalter(pg_session, False)

    text = client.get(f"/customers/{kunde.id}/bearbeiten").text

    assert "Schnittstellen-ID" not in text


def test_mit_schalter_ist_die_schnittstellen_id_da(client, pg_session):
    kunde = _kunde(pg_session)
    _schalter(pg_session, True)

    text = client.get(f"/customers/{kunde.id}/bearbeiten").text

    assert "Schnittstellen-ID" in text
    assert str(kunde.id) in text


def test_ohne_schalter_keine_schnittstellen_id_in_der_kundenliste(client, pg_session):
    _kunde(pg_session)
    _schalter(pg_session, False)

    text = client.get("/customers/").text

    assert "SCHNITTSTELLEN-ID" not in text.upper()


def test_ohne_schalter_kein_menuepunkt(client, pg_session):
    _schalter(pg_session, False)

    text = client.get("/customers/").text

    assert "/uebergaben" not in text


def test_mit_schalter_gibt_es_den_menuepunkt(client, pg_session):
    _schalter(pg_session, True)

    text = client.get("/customers/").text

    assert "/uebergaben" in text
