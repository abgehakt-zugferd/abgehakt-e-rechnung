"""Sendeprotokoll und Zweitversand (#146).

Warum das ein Integrationstest gegen echtes Postgres ist: der Kern der Sache ist
der `before_flush`-Guard (`invoice_guard`), und den beweist kein Mock. Bis heute
setzte der Router `datev_sent_at` bedingungslos — der ZWEITE Versand schickte die
Mail und starb danach am Guard („nach dem Setzen unveränderlich"). Die Nutzerin
sah eine Fehlerseite und wusste nicht, ob gesendet wurde. Genau das ist hier
festgenagelt.
"""
import uuid
from datetime import date
from unittest.mock import patch

import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceSendLog
from app.services import datev_email


def teardown_function():
    app.dependency_overrides.clear()


def _valid_mustang():
    return {"is_valid": True, "raw": "Parsed PDF:valid\nXML:valid",
            "errors": [], "warnings": []}


def _seed(pg_session, status="issued", pdf="RE.pdf"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München",
                 country="DE", email="kunde@example.de")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-LOG-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status=status, pdf_filename=pdf)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _logs(pg_session, invoice_id):
    return (pg_session.query(InvoiceSendLog)
            .filter(InvoiceSendLog.invoice_id == invoice_id)
            .order_by(InvoiceSendLog.sent_at).all())


def test_erster_versand_schreibt_protokollzeile(pg_session):
    inv = _seed(pg_session)
    with patch.object(datev_email, "send_invoice"), \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()):
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden",
                                     data={"cc_email": "ablage@example.de"})
    assert r.status_code == 303
    pg_session.expire_all()
    zeilen = _logs(pg_session, inv.id)
    assert len(zeilen) == 1
    assert zeilen[0].success is True
    assert zeilen[0].to_email == "kunde@example.de"
    assert zeilen[0].cc_email == "ablage@example.de"
    assert zeilen[0].datev_bcc is True
    assert zeilen[0].error is None


def test_zweiter_versand_ohne_guard_fehler(pg_session):
    """Der Regressionstest: zweimal senden darf NICHT am invoice_guard scheitern,
    und `datev_sent_at` bleibt der Erstversand (#98 P0.3 gilt weiter)."""
    inv = _seed(pg_session)
    with patch.object(datev_email, "send_invoice"), \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()):
        c = _client(pg_session)
        assert c.post(f"/invoices/{inv.id}/datev-senden").status_code == 303
        pg_session.expire_all()
        erst = pg_session.query(Invoice).filter(Invoice.id == inv.id).first().datev_sent_at
        assert erst is not None
        r2 = c.post(f"/invoices/{inv.id}/datev-senden")

    assert r2.status_code == 303, r2.text
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at == erst          # unverfälschter Erstversand
    assert len(_logs(pg_session, inv.id)) == 2   # beide Versuche protokolliert


def test_fehlversuch_wird_protokolliert(pg_session):
    """Die SMTP-Meldung ist der eigentliche Wert des Protokolls — bei einer
    gesperrten Empfängeradresse ist sie das Einzige, was weiterhilft."""
    inv = _seed(pg_session)
    with patch.object(datev_email, "send_invoice",
                      side_effect=datev_email.EmailError("SMTP-Fehler: 550 blocked")), \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()):
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")

    assert r.status_code == 400
    pg_session.expire_all()
    zeilen = _logs(pg_session, inv.id)
    assert len(zeilen) == 1
    assert zeilen[0].success is False
    assert "550 blocked" in zeilen[0].error
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at is None          # ein Fehlversuch ist kein Versand


def test_nach_fehlversuch_gelingt_der_zweite_und_setzt_den_zeitstempel(pg_session):
    inv = _seed(pg_session)
    c = _client(pg_session)
    with patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()):
        with patch.object(datev_email, "send_invoice",
                          side_effect=datev_email.EmailError("SMTP-Fehler: 550 blocked")):
            assert c.post(f"/invoices/{inv.id}/datev-senden").status_code == 400
        with patch.object(datev_email, "send_invoice"):
            assert c.post(f"/invoices/{inv.id}/datev-senden").status_code == 303

    pg_session.expire_all()
    zeilen = _logs(pg_session, inv.id)
    assert [z.success for z in zeilen] == [False, True]
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at is not None


@pytest.mark.parametrize("pdf,grund", [
    ("RE-2026-x_visual.pdf", "Visual-PDF"),
    (None, "kein PDF"),
])
def test_abbruch_vor_dem_versand_schreibt_keine_zeile(pg_session, pdf, grund):
    """Ein Versand, der gar nicht stattgefunden hat, gehört nicht ins
    Versandprotokoll — sonst wäre die Liste voller Zeilen ohne Zustellversuch."""
    inv = _seed(pg_session, pdf=pdf)
    with patch.object(datev_email, "send_invoice") as send:
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 400, grund
    send.assert_not_called()
    pg_session.expire_all()
    assert _logs(pg_session, inv.id) == []


def test_bezahlte_rechnung_darf_erneut_gesendet_werden(pg_session):
    """`paid` ist ein Endstatus, aber kein Grund, den Beleg nicht noch einmal
    verschicken zu können — die Route erlaubt es, die Oberfläche zeigt es jetzt auch."""
    inv = _seed(pg_session, status="paid")
    with patch.object(datev_email, "send_invoice"), \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()):
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 303
    assert len(_logs(pg_session, inv.id)) == 1


def test_detailseite_zeigt_das_versandprotokoll(pg_session):
    inv = _seed(pg_session)
    with patch.object(datev_email, "send_invoice",
                      side_effect=datev_email.EmailError("SMTP-Fehler: 550 blocked")), \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()):
        _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")

    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert r.status_code == 200
    assert "VERSANDPROTOKOLL" in r.text
    assert "550 blocked" in r.text
