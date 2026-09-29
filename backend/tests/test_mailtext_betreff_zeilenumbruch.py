"""Befund Review: Zeilenumbruch im Betreff und offenes Versandprotokoll.

(a) Speichern ablehnen, (b) ersetzter Betreff pruefen, (c) Protokoll nie offen lassen.
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceSendLog
from app.services import datev_email, mailtext


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session, *, raise_server_exceptions=True):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(
        app,
        follow_redirects=False,
        raise_server_exceptions=raise_server_exceptions,
    )


def _valid_mustang():
    return {
        "is_valid": True,
        "raw": "Parsed PDF:valid\nXML:valid",
        "errors": [],
        "warnings": [],
    }


def _config(pg_session, **werte):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if not cfg:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    for k, v in werte.items():
        setattr(cfg, k, v)
    pg_session.commit()
    return cfg


def _rechnung_mit_pdf(pg_session, *, kundenname="Kunde GmbH"):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name=kundenname,
        address_line1="Weg 1",
        zip_code="80331",
        city="München",
        country="DE",
        email="kunde@example.de",
    )
    pg_session.add(c)
    pg_session.flush()
    name = f"RE-BR-{uuid.uuid4().hex[:6]}.pdf"
    inv = Invoice(
        invoice_number=name.replace(".pdf", ""),
        customer_id=c.id,
        issue_date=date(2026, 9, 1),
        due_date=date(2026, 9, 28),
        currency="EUR",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        status="issued",
        pdf_filename=name,
        document_language="de",
    )
    pg_session.add(inv)
    pg_session.commit()
    pdf = get_settings().storage_path / "pdfs" / name
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\ntrailer<<>>\n%%EOF\n")
    return inv


def test_betreff_mit_zeilenumbruch_wird_beim_speichern_abgelehnt(pg_session):
    _config(pg_session, mail_betreff_de="Alt ok")
    r = _client(pg_session).post(
        "/settings/mailtext",
        data={
            "mail_betreff_de": "Rechnung\nBcc: attacker@example.org",
            "mail_text_de": "Rumpf mit\nZeilenumbruch ist ok",
            "mail_betreff_en": "",
            "mail_text_en": "",
        },
    )
    assert r.status_code == 200
    assert "Zeilenumbruch" in r.text or "Zeile" in r.text
    assert "Rechnung\nBcc: attacker@example.org" in r.text or "attacker@example.org" in r.text
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.mail_betreff_de == "Alt ok"
    assert cfg.mail_text_de is None or cfg.mail_text_de != "Rumpf mit\nZeilenumbruch ist ok"


def test_rumpf_mit_zeilenumbruch_darf_gespeichert_werden(pg_session):
    r = _client(pg_session).post(
        "/settings/mailtext",
        data={
            "mail_betreff_de": "Rechnung {rechnungsnummer}",
            "mail_text_de": "Zeile eins\n\nZeile zwei {firma}",
            "mail_betreff_en": "",
            "mail_text_en": "",
        },
    )
    assert r.status_code == 303
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert "Zeile eins\n\nZeile zwei" in cfg.mail_text_de


def test_ersetzter_betreff_mit_umbruch_aus_platzhalter_wirft():
    with pytest.raises(mailtext.BetreffMitZeilenumbruchError):
        mailtext.rechnungsmail(
            SimpleNamespace(
                invoice_number="RE-1",
                document_language="de",
                gross_total=Decimal("10"),
                currency="EUR",
                due_date=date(2026, 9, 28),
                customer=SimpleNamespace(name="Acme\nBcc: evil@example.org"),
            ),
            SimpleNamespace(name="Firma", address_line1="", zip_code="", city=""),
            SimpleNamespace(
                mail_betreff_de="An {kunde}",
                mail_text_de=None,
                mail_betreff_en=None,
                mail_text_en=None,
            ),
        )


def test_versand_mit_zeilenumbruch_im_betreff_schliesst_protokoll(pg_session):
    """Ganzer Weg: gespeicherter Umbruch-Betreff, Versand, Protokoll nicht offen.

    Der Betreff wird hier direkt in die DB gelegt (Stand vor der Speicherpruefung),
    damit der Schaden am Versandnachweis unabhaengig von (a) gemessen wird.
    """
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    firma.name = "Kanzlei Musterfrau"
    firma.address_line1 = "Musterweg 3"
    firma.zip_code = "80331"
    firma.city = "München"
    pg_session.commit()
    _config(
        pg_session,
        mail_betreff_de="Rechnung\nBcc: attacker@example.org",
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_from="rechnung@kanzlei.de",
        smtp_use_tls=False,
    )
    inv = _rechnung_mit_pdf(pg_session)

    server = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = server

    with patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()), \
         patch.object(datev_email.smtplib, "SMTP", return_value=smtp_cm):
        r = _client(pg_session, raise_server_exceptions=False).post(
            f"/invoices/{inv.id}/datev-senden"
        )

    assert r.status_code in (400, 500)
    server.send_message.assert_not_called()
    pg_session.expire_all()
    zeilen = (
        pg_session.query(InvoiceSendLog)
        .filter(InvoiceSendLog.invoice_id == inv.id)
        .all()
    )
    assert len(zeilen) == 1
    assert zeilen[0].success is False
    assert zeilen[0].error


def test_unerwartete_ausnahme_beim_versand_schliesst_protokoll(pg_session):
    _config(pg_session, smtp_host="smtp.test")
    inv = _rechnung_mit_pdf(pg_session)
    with patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()), \
         patch.object(datev_email, "send_invoice", side_effect=RuntimeError("unvorhergesehen")):
        try:
            _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")
        except RuntimeError:
            pass

    pg_session.expire_all()
    zeilen = (
        pg_session.query(InvoiceSendLog)
        .filter(InvoiceSendLog.invoice_id == inv.id)
        .all()
    )
    assert len(zeilen) == 1
    assert zeilen[0].success is False
    assert "unvorhergesehen" in (zeilen[0].error or "")
