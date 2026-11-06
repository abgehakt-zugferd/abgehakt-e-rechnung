"""Schlussrechnung (#259, Teil 1): wann eine Anzahlung wieder frei wird.

Verworfener Entwurf, manuell stornierte und per Gutschrift aufgehobene
Schlussrechnung geben die Anzahlung frei (aktiv=false, Zeile bleibt als
Nachweis); das Zurueckholen nimmt sie wieder, solange sie frei ist.
"""
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.anzahlung_verrechnung import AnzahlungVerrechnung
from app.models.invoice import Invoice
from app.services import mustang, pdfa
from tests.helpers.schlussrechnung import anzahlung, kunde, payload, schluss_ueber_formular

settings = get_settings()


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _aktiv(pg_session, az):
    pg_session.expire_all()
    zeilen = pg_session.query(AnzahlungVerrechnung).filter_by(anzahlung_id=az.id).all()
    return [z.aktiv for z in zeilen]


def _angebot(client, k):
    r = client.get(f"/invoices/anzahlungen?customer_id={k.id}")
    return {z["nummer"] for z in r.json()}


def _entwurf(pg_session):
    k = kunde(pg_session)
    az = anzahlung(pg_session, k)
    client = _client(pg_session)
    return k, az, client, schluss_ueber_formular(pg_session, client, k, [az])


def test_verworfener_entwurf_gibt_die_anzahlung_frei(pg_session):
    k, az, client, entwurf = _entwurf(pg_session)
    assert _aktiv(pg_session, az) == [True]
    assert client.post(f"/invoices/{entwurf.id}/verwerfen").status_code == 303
    assert _aktiv(pg_session, az) == [False]
    assert _angebot(client, k) == {az.invoice_number}
    # Die Anzahlung ist wieder verrechenbar, auch in einer neuen Rechnung.
    assert client.post("/invoices/neu", data=payload(k, [az])).status_code == 303


def test_zurueckgeholter_entwurf_verrechnet_wieder(pg_session):
    k, az, client, entwurf = _entwurf(pg_session)
    client.post(f"/invoices/{entwurf.id}/verwerfen")
    assert client.post(f"/invoices/{entwurf.id}/zurueckholen").status_code == 303
    assert _aktiv(pg_session, az) == [True]


def test_zurueckholen_scheitert_wenn_die_anzahlung_inzwischen_vergeben_ist(pg_session):
    k, az, client, entwurf = _entwurf(pg_session)
    client.post(f"/invoices/{entwurf.id}/verwerfen")
    assert client.post("/invoices/neu", data=payload(k, [az])).status_code == 303
    r = client.post(f"/invoices/{entwurf.id}/zurueckholen")
    assert r.status_code == 400
    assert "schon in einer anderen Rechnung verrechnet" in r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, entwurf.id).status == "discarded"


def _gestellt(pg_session, entwurf):
    """Entwurf als gestellt markieren, ohne die Pipeline (Status-Wirkung genuegt)."""
    entwurf.status = "issued"
    pg_session.commit()


def test_manuell_stornierte_schlussrechnung_gibt_die_anzahlung_frei(pg_session):
    k, az, client, entwurf = _entwurf(pg_session)
    _gestellt(pg_session, entwurf)
    r = client.post(f"/invoices/{entwurf.id}/status", data={"new_status": "cancelled"})
    assert r.status_code == 303, r.text
    assert _aktiv(pg_session, az) == [False]


def test_bezahlen_der_schlussrechnung_gibt_nichts_frei(pg_session):
    k, az, client, entwurf = _entwurf(pg_session)
    _gestellt(pg_session, entwurf)
    r = client.post(f"/invoices/{entwurf.id}/status",
                    data={"new_status": "paid", "bezahlt_am": "2026-08-20"})
    assert r.status_code == 303, r.text
    assert _aktiv(pg_session, az) == [True]


@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
def test_gestellte_gutschrift_zur_schlussrechnung_gibt_die_anzahlung_frei(pg_session):
    k, az, client, entwurf = _entwurf(pg_session)
    nummern = [entwurf.invoice_number]
    try:
        assert client.post(f"/invoices/{entwurf.id}/finalisieren").status_code == 303
        r = client.post(f"/invoices/{entwurf.id}/storno")
        assert r.status_code == 303, r.text
        storno_id = r.headers["location"].rsplit("/", 1)[1]
        pg_session.expire_all()
        storno = pg_session.get(Invoice, storno_id)
        nummern.append(storno.invoice_number)
        # Ein Storno-ENTWURF hebt nichts auf.
        assert _aktiv(pg_session, az) == [True]
        assert client.post(f"/invoices/{storno_id}/finalisieren").status_code == 303
        assert _aktiv(pg_session, az) == [False]
    finally:
        for nummer in nummern:
            for pfad in (settings.storage_path / "pdfs" / f"{nummer}.pdf",
                         settings.storage_path / "pdfs" / f"{nummer}_visual.pdf",
                         settings.storage_path / "xml" / f"{nummer}.xml"):
                pfad.unlink(missing_ok=True)
