"""TESTINSTANZ: GUI-Kennzeichnung und Mail-Umleitung."""

from email.message import EmailMessage
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config import get_settings
from app.services import datev_email


@pytest.fixture
def testinstanz_settings(monkeypatch):
    monkeypatch.setattr(get_settings(), "installation_mode", "testinstanz")
    monkeypatch.setattr(get_settings(), "testinstanz_mail_to", "test@postbox.de")


def test_startup_blockiert_testinstanz_ohne_mail(monkeypatch):
    from app.main import validate_startup_config

    monkeypatch.setattr(get_settings(), "installation_mode", "testinstanz")
    monkeypatch.setattr(get_settings(), "testinstanz_mail_to", "")
    with pytest.raises(RuntimeError, match="TESTINSTANZ_MAIL_TO"):
        validate_startup_config(get_settings())


def test_banner_im_dashboard(client, testinstanz_settings):
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "data-testinstanz-banner" in r.text
    assert "TESTINSTANZ" in r.text


def test_rechnungsmail_nur_an_testpostbox(testinstanz_settings, tmp_path):
    pdf = tmp_path / "RE-2026-001.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")

    cfg = type(
        "Cfg",
        (),
        {
            "smtp_host": "smtp.example.de",
            "smtp_port": 587,
            "smtp_user": "u",
            "smtp_password": "p",
            "smtp_from": "rechnung@example.de",
            "smtp_use_tls": True,
            "datev_bcc_email": "datev@example.de",
        },
    )()

    server = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = server

    with patch.object(datev_email, "_get_effective_smtp_config", return_value=cfg), \
         patch.object(datev_email.smtplib, "SMTP", return_value=smtp_cm):
        datev_email.send_invoice(
            to_email="kunde@example.de",
            invoice_number="RE-2026-001",
            customer_name="Kunde",
            pdf_path=pdf,
            bcc_datev=True,
            cc_email="cc@example.de",
        )

    msg = server.send_message.call_args[0][0]
    assert isinstance(msg, EmailMessage)
    assert msg["To"] == "test@postbox.de"
    assert msg["Cc"] is None
    assert msg["Bcc"] is None
    assert msg["Subject"] == "[TESTINSTANZ] Rechnung RE-2026-001"
    body = ""
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            body = part.get_content()
            break
    assert "kunde@example.de" in body
    assert "datev@example.de" in body


def test_smtp_testmail_nur_an_testpostbox(testinstanz_settings):
    cfg = type(
        "Cfg",
        (),
        {
            "smtp_host": "smtp.example.de",
            "smtp_port": 587,
            "smtp_user": "u",
            "smtp_password": "p",
            "smtp_from": "rechnung@example.de",
            "smtp_use_tls": True,
            "datev_bcc_email": "",
        },
    )()

    server = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = server

    with patch.object(datev_email, "_get_effective_smtp_config", return_value=cfg), \
         patch.object(datev_email.smtplib, "SMTP", return_value=smtp_cm):
        datev_email.send_test_email("anderer@example.de")

    msg = server.send_message.call_args[0][0]
    assert msg["To"] == "test@postbox.de"
    assert msg["Subject"].startswith("[TESTINSTANZ]")
