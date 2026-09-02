"""
Einwilligung vor VIES-Abfragen: URL sichtbar, kein Abruf ohne Bestaetigung,
kein Abruf beim Speichern.

Waechter fuer ust_id_vies/consent.html und die Router customers/settings.
"""
import re
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.services.ust_id_pruefung import VIES_ENDPOINT
from tests.factories import orm_customer
from tests.probe_daten import UST_DE_PROBE, UST_DE_PROBE_2

KNOPF = re.compile(r"<button\b[^>]*>", re.IGNORECASE)


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    with TestClient(app, follow_redirects=False) as c:
        yield c
    app.dependency_overrides.clear()


def _kunde_mit_ust(pg_session):
    kunde = orm_customer(
        customer_number="K-VIES-1",
        vat_id=UST_DE_PROBE,
        vat_id_checked_at=None,
        vat_id_check_valid=None,
    )
    pg_session.add(kunde)
    pg_session.commit()
    pg_session.refresh(kunde)
    return kunde


def _zustimmungsseite(client, kunde_id, monkeypatch) -> str:
    monkeypatch.setattr(
        "app.routers.customers.pruefe_ust_id_vies",
        lambda *a, **k: pytest.fail("vor der Bestaetigung darf VIES nicht aufgerufen werden"),
    )
    r = client.post(f"/customers/{kunde_id}/ust-id-pruefen")
    assert r.status_code == 200
    assert 'data-seite="vies-zustimmung"' in r.text
    return r.text.split('data-seite="vies-zustimmung"')[1]


def test_zustimmung_zeigt_vies_url(client, pg_session, monkeypatch):
    kunde = _kunde_mit_ust(pg_session)
    inhalt = _zustimmungsseite(client, kunde.id, monkeypatch)
    assert VIES_ENDPOINT in inhalt


def test_zustimmung_zeigt_ust_id_und_name(client, pg_session, monkeypatch):
    kunde = _kunde_mit_ust(pg_session)
    inhalt = _zustimmungsseite(client, kunde.id, monkeypatch)
    assert UST_DE_PROBE in inhalt
    assert kunde.name in inhalt


def test_zustimmung_benennt_ip_adresse(client, pg_session, monkeypatch):
    kunde = _kunde_mit_ust(pg_session)
    inhalt = _zustimmungsseite(client, kunde.id, monkeypatch)
    assert "IP-Adresse" in inhalt


def test_zustimmung_kein_abruf_beim_speichern(client, pg_session, monkeypatch):
    monkeypatch.setattr(
        "app.routers.customers.pruefe_ust_id_vies",
        lambda *a, **k: pytest.fail("Speichern darf VIES nicht aufrufen"),
    )
    r = client.post(
        "/customers/neu",
        data={
            "name": "Neu GmbH",
            "customer_number": "K-VIES-NEU",
            "address_line1": "Weg 2",
            "zip_code": "10115",
            "city": "Berlin",
            "country": "DE",
            "vat_id": UST_DE_PROBE_2,
            "is_active": "1",
        },
    )
    assert r.status_code == 303
    kunde = pg_session.query(Customer).filter_by(customer_number="K-VIES-NEU").first()
    assert kunde is not None
    assert kunde.vat_id == UST_DE_PROBE_2
    assert kunde.vat_id_checked_at is None


def test_knoepfe_der_zustimmung_sind_als_knopf_erkennbar(client, pg_session, monkeypatch):
    kunde = _kunde_mit_ust(pg_session)
    inhalt = _zustimmungsseite(client, kunde.id, monkeypatch)
    knoepfe = KNOPF.findall(inhalt)
    assert knoepfe
    for k in knoepfe:
        assert "btn-" in k


def test_mit_bestaetigung_wird_vies_gerufen(client, pg_session, monkeypatch):
    kunde = _kunde_mit_ust(pg_session)
    gesehen = {}

    def fake_vies(ust_id, trader_name, requester=None, **kw):
        gesehen["ust_id"] = ust_id
        gesehen["trader_name"] = trader_name
        from app.services.ust_id_pruefung import UstIdPruefungErgebnis
        return UstIdPruefungErgebnis(
            verfuegbar=True,
            gueltig=True,
            registrierter_name="Test",
            registrierte_adresse=None,
            name_abgleich="stimmt",
            fehlercode=None,
            geprueft_am=datetime.now(timezone.utc),
        )

    monkeypatch.setattr("app.routers.customers.pruefe_ust_id_vies", fake_vies)
    r = client.post(
        f"/customers/{kunde.id}/ust-id-pruefen",
        data={"bestaetigt": "1"},
    )
    assert r.status_code == 303
    assert gesehen["ust_id"] == UST_DE_PROBE
    pg_session.refresh(kunde)
    assert kunde.vat_id_check_valid is True
