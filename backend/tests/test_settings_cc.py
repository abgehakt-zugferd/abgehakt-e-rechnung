"""CC-Empfänger der Rechnungsmail (#147).

Drei Ebenen, weil die Adresse durch drei Hände geht: Einstellungen speichern sie,
die Detailseite belegt das Feld damit vor, der Sende-Router reicht die tatsächlich
abgeschickte Adresse an den Mailversand weiter (nicht die gespeicherte — das Feld
ist pro Versand überschreibbar).
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services import datev_email


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _config(pg_session, **werte):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if not cfg:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    for k, v in werte.items():
        setattr(cfg, k, v)
    pg_session.commit()
    return cfg


def test_einstellungen_speichern_cc_adresse(pg_session):
    r = _client(pg_session).post("/settings/datev", data={
        "datev_bcc_email": "datev@example.de",
        "invoice_cc_email": "  ablage@example.de  ",
    })
    assert r.status_code == 303
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.invoice_cc_email == "ablage@example.de"


def test_leeres_cc_feld_wird_zu_null(pg_session):
    """Leer heißt „keine Kopie" — nicht der leere String. Ein leerer String im
    Cc-Kopf lässt manche Mailserver die Nachricht zurückweisen."""
    _config(pg_session, invoice_cc_email="alt@example.de")
    r = _client(pg_session).post("/settings/datev", data={
        "datev_bcc_email": "datev@example.de", "invoice_cc_email": ""})
    assert r.status_code == 303
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.invoice_cc_email is None


def _seed_issued(pg_session):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München",
                 country="DE", email="kunde@example.de")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-CC-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status="issued", pdf_filename="RE.pdf")
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_detailseite_belegt_cc_feld_vor(pg_session):
    inv = _seed_issued(pg_session)
    _config(pg_session, smtp_host="smtp.example.de", datev_bcc_email="datev@example.de",
            invoice_cc_email="ablage@example.de")
    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert r.status_code == 200
    assert 'name="cc_email"' in r.text
    assert 'value="ablage@example.de"' in r.text


def test_send_router_reicht_abgeschickte_cc_adresse_durch(pg_session):
    """Verbindlich ist das Formularfeld, nicht der gespeicherte Vorschlag —
    sonst ließe sich die Kopie pro Versand nicht ändern oder weglassen."""
    inv = _seed_issued(pg_session)
    _config(pg_session, invoice_cc_email="ablage@example.de")
    valid = {"is_valid": True, "raw": "Parsed PDF:valid\nXML:valid", "errors": [], "warnings": []}
    with patch.object(datev_email, "send_invoice") as send, \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=valid):
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden",
                                     data={"cc_email": "anders@example.de"})
    assert r.status_code == 303
    assert send.call_args.kwargs["cc_email"] == "anders@example.de"
