"""VIES-Pruefung verliert keine Eingaben (#274): Einwilligung bestaetigt, dann wird das
ganze Formular wie beim normalen Speichern gespeichert und erst danach geprueft.

Naht: die Routen (POST .../bearbeiten bzw. /settings/firma mit danach_vies=1).
Attrappe nur an der Systemgrenze (VIES-Abruf); sie zaehlt Aufrufe als Beobachtung.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.services.pflichtangaben import RECHTSFORMEN
from app.services.ust_id_pruefung import UstIdPruefungErgebnis
from tests.factories import orm_customer
from tests.probe_daten import UST_DE_PROBE, UST_DE_PROBE_2


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


class ViesAttrappe:
    def __init__(self, gueltig=True):
        self.aufrufe = []
        self.gueltig = gueltig

    def __call__(self, ust_id, trader_name, requester=None, **kw):
        self.aufrufe.append((ust_id, trader_name))
        return UstIdPruefungErgebnis(
            verfuegbar=True, gueltig=self.gueltig, registrierter_name="Test",
            registrierte_adresse=None, name_abgleich="stimmt", fehlercode=None,
            geprueft_am=datetime.now(timezone.utc),
        )


@pytest.fixture
def vies_kunde(monkeypatch):
    a = ViesAttrappe()
    monkeypatch.setattr("app.routers.customers.pruefe_ust_id_vies", a)
    return a


@pytest.fixture
def vies_firma(monkeypatch):
    a = ViesAttrappe()
    monkeypatch.setattr("app.routers.settings.pruefe_ust_id_vies", a)
    return a


def _kunde(pg_session):
    k = orm_customer(
        customer_number="K-274", country="DE", vat_id=UST_DE_PROBE,
        vat_id_checked_at=None, vat_id_check_valid=None,
    )
    pg_session.add(k)
    pg_session.commit()
    pg_session.refresh(k)
    return k


def _kundenformular(**over):
    daten = {
        "name": "Kunde GmbH", "customer_number": "K-274",
        "address_line1": "Neue Strasse 5", "zip_code": "1010", "city": "Wien",
        "country": "AT", "vat_id": UST_DE_PROBE_2, "is_active": "1",
    }
    daten.update(over)
    return daten


def _lade(pg_session, kunde_id):
    pg_session.expire_all()
    return pg_session.query(Customer).filter(Customer.id == kunde_id).one()


def test_speichern_und_pruefen_speichert_ganzes_formular_dann_vies(
    client, pg_session, vies_kunde,
):
    kunde = _kunde(pg_session)
    r = client.post(
        f"/customers/{kunde.id}/bearbeiten",
        data=_kundenformular(danach_vies="1", bestaetigt="1"),
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/customers/{kunde.id}/bearbeiten"
    k = _lade(pg_session, kunde.id)
    assert k.country == "AT"
    assert k.city == "Wien"
    assert k.vat_id == UST_DE_PROBE_2
    assert k.vat_id_checked_at is not None
    assert k.vat_id_check_valid is True
    assert vies_kunde.aufrufe == [(UST_DE_PROBE_2, "Kunde GmbH")]


def test_ohne_einwilligung_nichts_gespeichert_keine_verbindung(
    client, pg_session, vies_kunde,
):
    kunde = _kunde(pg_session)
    r = client.post(
        f"/customers/{kunde.id}/bearbeiten", data=_kundenformular(danach_vies="1"),
    )
    assert r.status_code == 400
    k = _lade(pg_session, kunde.id)
    assert k.country == "DE"
    assert k.vat_id == UST_DE_PROBE
    assert vies_kunde.aufrufe == []


def test_formularfehler_keine_abfrage_eingaben_bleiben_im_formular(
    client, pg_session, vies_kunde,
):
    kunde = _kunde(pg_session)
    r = client.post(
        f"/customers/{kunde.id}/bearbeiten",
        data=_kundenformular(cc_emails="kein-mailadresse", danach_vies="1", bestaetigt="1"),
    )
    assert r.status_code == 200
    assert vies_kunde.aufrufe == []
    k = _lade(pg_session, kunde.id)
    assert k.country == "DE"
    assert k.vat_id_checked_at is None


def test_normales_speichern_ohne_danach_vies_ruft_vies_nicht(
    client, pg_session, vies_kunde,
):
    kunde = _kunde(pg_session)
    r = client.post(f"/customers/{kunde.id}/bearbeiten", data=_kundenformular())
    assert r.status_code == 303
    assert r.headers["location"] == "/customers"
    assert vies_kunde.aufrufe == []


def _firmenformular(**over):
    daten = {
        "name": "Eigene GmbH", "address_line1": "Neue Strasse 5", "zip_code": "10115",
        "city": "Berlin", "country": "DE", "vat_id": UST_DE_PROBE_2,
        "tax_number": "", "rechtsform": next(iter(RECHTSFORMEN)),
        "payment_terms_default": "14 Tage", "payment_terms_default_en": "14 days",
    }
    daten.update(over)
    return daten


def _firma(pg_session):
    pg_session.expire_all()
    return pg_session.query(Company).filter(Company.id == 1).one()


def test_firma_speichern_und_pruefen(client, pg_session, vies_firma):
    r = client.post(
        "/settings/firma", data=_firmenformular(danach_vies="1", bestaetigt="1"),
    )
    assert r.status_code == 303
    f = _firma(pg_session)
    assert f.address_line1 == "Neue Strasse 5"
    assert f.vat_id == UST_DE_PROBE_2
    assert f.vat_id_check_valid is True
    assert vies_firma.aufrufe == [(UST_DE_PROBE_2, "Eigene GmbH")]


def test_firma_ohne_einwilligung_nichts_gespeichert(client, pg_session, vies_firma):
    client.post("/settings/firma", data=_firmenformular(address_line1="Alt 1"))
    r = client.post(
        "/settings/firma",
        data=_firmenformular(address_line1="Neu 2", danach_vies="1"),
    )
    assert r.status_code == 400
    assert _firma(pg_session).address_line1 == "Alt 1"
    assert vies_firma.aufrufe == []


def test_firma_formularfehler_keine_abfrage(client, pg_session, vies_firma):
    r = client.post(
        "/settings/firma",
        data=_firmenformular(bank_iban="DE00", danach_vies="1", bestaetigt="1"),
    )
    assert r.status_code == 200
    assert vies_firma.aufrufe == []
