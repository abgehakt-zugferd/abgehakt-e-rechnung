"""
Einwilligungsdialog vor VIES-Abfragen: URL im Dialog, kein Abruf ohne Bestaetigung,
kein verschachteltes Formular (Button darf nicht Speichern triggern).

Waechter: partials/ust_id_vies_dialog.html
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


def _bearbeiten_seite(client, kunde_id) -> str:
    r = client.get(f"/customers/{kunde_id}/bearbeiten")
    assert r.status_code == 200
    assert 'data-seite="vies-zustimmung"' in r.text
    return r.text.split('data-seite="vies-zustimmung"')[1]


def test_dialog_auf_bearbeiten_seite_zeigt_vies_url(client, pg_session):
    kunde = _kunde_mit_ust(pg_session)
    inhalt = _bearbeiten_seite(client, kunde.id)
    assert VIES_ENDPOINT in inhalt


def test_dialog_zeigt_gespeicherte_ust_id(client, pg_session):
    kunde = _kunde_mit_ust(pg_session)
    html = client.get(f"/customers/{kunde.id}/bearbeiten").text
    assert UST_DE_PROBE in html
    assert kunde.name in html


def test_dialog_benennt_ip_adresse(client, pg_session):
    kunde = _kunde_mit_ust(pg_session)
    inhalt = _bearbeiten_seite(client, kunde.id)
    assert "IP-Adresse" in inhalt


def test_vies_button_ist_kein_form_submit(client, pg_session):
    kunde = _kunde_mit_ust(pg_session)
    html = client.get(f"/customers/{kunde.id}/bearbeiten").text
    assert "js-vies-consent-open" in html
    assert 'class="btn-secondary js-vies-consent-open"' in html or "js-vies-consent-open" in html
    # Kein verschachteltes <form> fuer VIES innerhalb des Kundenformulars
    assert html.count("<form") == 2  # Kundenformular + Dialog-Formular ausserhalb


def test_speichern_ruft_vies_nicht_auf(client, pg_session, monkeypatch):
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


def test_post_ohne_einwilligung_wird_abgelehnt(client, pg_session):
    kunde = _kunde_mit_ust(pg_session)
    r = client.post(f"/customers/{kunde.id}/ust-id-pruefen")
    assert r.status_code == 400


def test_knoepfe_im_dialog_sind_als_knopf_erkennbar(client, pg_session):
    kunde = _kunde_mit_ust(pg_session)
    inhalt = _bearbeiten_seite(client, kunde.id)
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
        data={
            "bestaetigt": "1",
            "check_vat_id": UST_DE_PROBE,
            "check_name": kunde.name,
        },
    )
    assert r.status_code == 303
    assert gesehen["ust_id"] == UST_DE_PROBE
    pg_session.refresh(kunde)
    assert kunde.vat_id_check_valid is True
