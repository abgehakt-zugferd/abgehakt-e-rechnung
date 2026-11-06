"""Schlussrechnung (#259, Teil 1): Auswahl der Anzahlung im Formular.

Naht: GET /invoices/anzahlungen (Angebot je Kunde), Formular Neuanlage und
Bearbeiten (POST mit `anzahlung_ids`, Vorbelegung im Bearbeiten-Formular).
"""
import json
import re

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.anzahlung_verrechnung import AnzahlungVerrechnung
from tests.helpers.ersatzrechnung import beleg, gutschrift
from tests.helpers.schlussrechnung import anzahlung, kunde, payload, schluss_ueber_formular


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _angebot(client, k, fuer=None):
    url = f"/invoices/anzahlungen?customer_id={k.id}" + (f"&fuer={fuer.id}" if fuer else "")
    r = client.get(url)
    assert r.status_code == 200, r.text
    return {z["nummer"] for z in r.json()}


def test_angeboten_werden_nur_bezahlte_unverrechnete_anzahlungen_des_kunden(pg_session):
    k = kunde(pg_session)
    frei = anzahlung(pg_session, k)
    unbezahlt = anzahlung(pg_session, k, status="issued", bezahlt=False)
    storniert = anzahlung(pg_session, k)
    gutschrift(pg_session, storniert)
    standard_bezahlt = anzahlung(pg_session, k, invoice_type=None)
    fremd = anzahlung(pg_session, kunde(pg_session, "Andere Probe GmbH"))
    verrechnet = anzahlung(pg_session, k)
    client = _client(pg_session)
    schluss_ueber_formular(pg_session, client, k, [verrechnet])
    angebot = _angebot(client, k)
    assert angebot == {frei.invoice_number}
    for nicht in (unbezahlt, storniert, standard_bezahlt, fremd, verrechnet):
        assert nicht.invoice_number not in angebot


def test_angebot_nennt_nummer_datum_und_brutto(pg_session):
    k = kunde(pg_session)
    az = anzahlung(pg_session, k)
    r = _client(pg_session).get(f"/invoices/anzahlungen?customer_id={k.id}")
    assert r.json() == [{"id": str(az.id), "nummer": az.invoice_number,
                         "datum": "08.07.2026", "brutto": "119,00 €"}]


def test_eigene_verrechnung_bleibt_im_angebot_des_entwurfs(pg_session):
    k = kunde(pg_session)
    az = anzahlung(pg_session, k)
    client = _client(pg_session)
    entwurf = schluss_ueber_formular(pg_session, client, k, [az])
    assert _angebot(client, k) == set()
    assert _angebot(client, k, fuer=entwurf) == {az.invoice_number}


def test_zweiter_entwurf_kann_verrechnete_anzahlung_nicht_waehlen(pg_session):
    k = kunde(pg_session)
    az = anzahlung(pg_session, k)
    client = _client(pg_session)
    schluss_ueber_formular(pg_session, client, k, [az])
    r = client.post("/invoices/neu", data=payload(k, [az]))
    assert r.status_code == 400
    assert "schon in einer anderen Rechnung verrechnet" in r.text


def test_bearbeiten_ersetzt_die_auswahl_und_zeigt_sie_vorbelegt(pg_session):
    k = kunde(pg_session)
    erste, zweite = anzahlung(pg_session, k), anzahlung(pg_session, k)
    client = _client(pg_session)
    entwurf = schluss_ueber_formular(pg_session, client, k, [erste])
    r = client.post(f"/invoices/{entwurf.id}/bearbeiten", data=payload(k, [zweite]))
    assert r.status_code == 303, r.text
    seite = client.get(f"/invoices/{entwurf.id}/bearbeiten").text
    vorgaben = json.loads(re.search(
        r'<script type="application/json" id="anzahlung-vorgaben">(.*?)</script>',
        seite, re.S).group(1))
    assert vorgaben == {"gewaehlt": [str(zweite.id)], "fuer": str(entwurf.id)}
    # Die ersetzte Anzahlung ist wieder frei, die Zeile bleibt nicht aktiv zurueck.
    assert _angebot(client, k, fuer=entwurf) == {erste.invoice_number, zweite.invoice_number}
    assert pg_session.query(AnzahlungVerrechnung).filter_by(anzahlung_id=erste.id).count() == 0


def test_bearbeiten_ohne_auswahl_loest_die_verrechnung(pg_session):
    k = kunde(pg_session)
    az = anzahlung(pg_session, k)
    client = _client(pg_session)
    entwurf = schluss_ueber_formular(pg_session, client, k, [az])
    r = client.post(f"/invoices/{entwurf.id}/bearbeiten", data=payload(k, []))
    assert r.status_code == 303, r.text
    assert _angebot(client, k) == {az.invoice_number}
