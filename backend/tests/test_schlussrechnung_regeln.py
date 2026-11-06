"""Schlussrechnung (#259, Teil 1): Sperren vor dem Finalisieren.

Naht: POST /invoices/neu (Entwurf mit Auswahl), dann POST /invoices/{id}/finalisieren.
Die Sperren greifen vor der Belegerzeugung; der Entwurf bleibt dabei unveraendert.
Der Gegenfall (0,00 Zahlbetrag ist gueltig) laeuft durch die echte Pipeline.
"""
import html
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.invoice import Invoice
from app.services import mustang, pdfa
from tests.helpers.ersatzrechnung import beleg, gutschrift
from tests.helpers.schlussrechnung import anzahlung, kunde, schluss_ueber_formular

settings = get_settings()


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _abgelehnt(pg_session, client, entwurf, erwartet):
    r = client.post(f"/invoices/{entwurf.id}/finalisieren")
    assert r.status_code == 400, r.text
    assert erwartet in html.unescape(r.text)
    pg_session.expire_all()
    assert pg_session.get(Invoice, entwurf.id).status == "draft"


def _fall(pg_session, az_kw=None, **form_kw):
    k = kunde(pg_session)
    az = anzahlung(pg_session, k, **(az_kw or {}))
    client = _client(pg_session)
    return k, az, client, schluss_ueber_formular(pg_session, client, k, [az], **form_kw)


def test_unbezahlte_anzahlung_blockiert(pg_session):
    _, _, client, entwurf = _fall(pg_session, {"status": "issued", "bezahlt": False})
    _abgelehnt(pg_session, client, entwurf, "noch nicht als bezahlt erfasst")


def test_anzahlung_eines_anderen_kunden_blockiert(pg_session):
    k, _, client, _ = _fall(pg_session)
    fremd = anzahlung(pg_session, kunde(pg_session, "Andere Probe GmbH"))
    entwurf = schluss_ueber_formular(pg_session, client, k, [fremd])
    _abgelehnt(pg_session, client, entwurf, "gehört zu einem anderen Kunden")


def test_andere_waehrung_blockiert(pg_session):
    _, _, client, entwurf = _fall(pg_session, {"currency": "USD"})
    _abgelehnt(pg_session, client, entwurf, "in einer anderen Währung")


def test_andere_steuerkategorie_blockiert(pg_session):
    _, _, client, entwurf = _fall(pg_session, {"kategorie": "AE", "satz": "0"})
    _abgelehnt(pg_session, client, entwurf, "andere Steuerkategorie")


def test_stornierte_anzahlung_blockiert(pg_session):
    k = kunde(pg_session)
    az = anzahlung(pg_session, k)
    client = _client(pg_session)
    entwurf = schluss_ueber_formular(pg_session, client, k, [az])
    gutschrift(pg_session, az)  # gestellte Gutschrift hebt die Anzahlung auf
    _abgelehnt(pg_session, client, entwurf, f"Die Anzahlung {az.invoice_number} ist storniert")


def test_mehr_als_eine_anzahlung_blockiert(pg_session):
    k = kunde(pg_session)
    client = _client(pg_session)
    entwurf = schluss_ueber_formular(
        pg_session, client, k, [anzahlung(pg_session, k), anzahlung(pg_session, k)])
    _abgelehnt(pg_session, client, entwurf, "mehr als eine Anzahlung")


def test_anzahlung_hoeher_als_rechnung_blockiert(pg_session):
    _, _, client, entwurf = _fall(pg_session, netto="50")  # 59,50 brutto gegen 119,00
    _abgelehnt(pg_session, client, entwurf, "höher als der Rechnungsbetrag")


def test_belegabzug_zugleich_blockiert(pg_session):
    _, _, client, entwurf = _fall(
        pg_session, extra={"abzug_betrag": "10", "abzug_grund": "Skonto"})
    _abgelehnt(pg_session, client, entwurf, "lassen sich nicht zugleich verrechnen")


def test_ersatzrechnung_blockiert(pg_session):
    k, _, client, entwurf = _fall(pg_session)
    entwurf.ersetzt_invoice_id = beleg(pg_session, k, status="issued").id
    pg_session.commit()
    _abgelehnt(pg_session, client, entwurf, "verweist schon auf eine vorausgegangene Rechnung")


def test_folgebeleg_blockiert(pg_session):
    k, _, client, entwurf = _fall(pg_session)
    entwurf.original_invoice_id = beleg(pg_session, k, status="issued").id
    pg_session.commit()
    _abgelehnt(pg_session, client, entwurf, "verweist schon auf eine vorausgegangene Rechnung")


@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
def test_anzahlung_gleich_rechnungsbetrag_ergibt_zahlbetrag_null(pg_session):
    k = kunde(pg_session)
    az = anzahlung(pg_session, k, netto="200")  # 238,00 brutto = Rechnungsbetrag
    client = _client(pg_session)
    entwurf = schluss_ueber_formular(pg_session, client, k, [az])
    nummer = entwurf.invoice_number
    try:
        r = client.post(f"/invoices/{entwurf.id}/finalisieren")
        assert r.status_code == 303, r.text
        pg_session.expire_all()
        xml = pg_session.get(Invoice, entwurf.id).zugferd_xml
        assert "<ram:TotalPrepaidAmount>238.00</ram:TotalPrepaidAmount>" in xml
        assert "<ram:DuePayableAmount>0.00</ram:DuePayableAmount>" in xml
    finally:
        for pfad in (settings.storage_path / "pdfs" / f"{nummer}.pdf",
                     settings.storage_path / "pdfs" / f"{nummer}_visual.pdf",
                     settings.storage_path / "xml" / f"{nummer}.xml"):
            pfad.unlink(missing_ok=True)
