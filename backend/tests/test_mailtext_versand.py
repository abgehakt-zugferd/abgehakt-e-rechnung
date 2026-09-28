"""Mailtext beim SMTP-Versand: Umlaute, MIME-Roundtrip, Testinstanz-Vorsatz."""
from email import message_from_bytes
from email.policy import default as email_policy
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.main import app
from app.models.app_config import AppConfig
from app.models.company import Company
from app.services import datev_email, mailtext
from tests.mailtext_fixtures import (
    client_fuer,
    config_setzen,
    firma_setzen,
    rechnung_anlegen,
    smtp_doppel,
)


def teardown_function():
    app.dependency_overrides.clear()


def test_umlaute_und_eszett_ueberleben_speichern_lesen_versand(pg_session, tmp_path):
    firma_setzen(pg_session, name="Büro Größe")
    text = "Grüße aus München für die Größe {rechnungsnummer}"
    r = client_fuer(pg_session).post(
        "/settings/mailtext",
        data={
            "mail_betreff_de": "Betreff Größe {rechnungsnummer}",
            "mail_text_de": text,
            "mail_betreff_en": "",
            "mail_text_en": "",
        },
    )
    assert r.status_code == 303
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.mail_text_de == text
    assert "Größe" in cfg.mail_betreff_de

    inv = rechnung_anlegen(pg_session, nummer="RE-Ü-1")
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    inhalt = mailtext.rechnungsmail(inv, firma, cfg)
    assert "Grüße aus München für die Größe RE-Ü-1" in inhalt.rumpf

    pdf = tmp_path / "re.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    gesendet, smtp_cls = smtp_doppel()
    with patch.object(
        datev_email,
        "_get_effective_smtp_config",
        return_value=SimpleNamespace(
            smtp_host="smtp.test",
            smtp_port=587,
            smtp_user="",
            smtp_password="",
            smtp_from="rechnung@kanzlei.de",
            smtp_use_tls=False,
            datev_bcc_email="",
        ),
    ), patch("smtplib.SMTP", smtp_cls):
        datev_email.send_invoice(
            "kunde@example.de", inhalt, pdf, bcc_datev=False, db=pg_session
        )
    assert "Grüße aus München für die Größe RE-Ü-1" in gesendet["body"]
    assert "Größe" in gesendet["subject"]


def test_umlaute_ueberleben_mime_roundtrip(pg_session, tmp_path):
    """Serialisieren und wieder einlesen: Umlaute und Eszett duerfen nicht kippen."""
    firma_setzen(pg_session, name="Büro Größe")
    config_setzen(
        pg_session,
        mail_betreff_de="Betreff Größe ß {rechnungsnummer}",
        mail_text_de="Grüße aus München für die Größe {rechnungsnummer}",
    )
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    inhalt = mailtext.rechnungsmail(
        rechnung_anlegen(pg_session, nummer="RE-MIME-1"), firma, cfg
    )
    pdf = tmp_path / "re.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    gesendet, smtp_cls = smtp_doppel()
    with patch.object(
        datev_email,
        "_get_effective_smtp_config",
        return_value=SimpleNamespace(
            smtp_host="smtp.test",
            smtp_port=587,
            smtp_user="",
            smtp_password="",
            smtp_from="rechnung@kanzlei.de",
            smtp_use_tls=False,
            datev_bcc_email="",
        ),
    ), patch("smtplib.SMTP", smtp_cls):
        datev_email.send_invoice(
            "kunde@example.de", inhalt, pdf, bcc_datev=False, db=pg_session
        )

    roh = gesendet["msg"].as_bytes()
    gelesen = message_from_bytes(roh, policy=email_policy)
    betreff = gelesen["Subject"]
    rumpf = gelesen.get_body(preferencelist=("plain",)).get_content()
    assert "Büro Größe" in rumpf or "Größe" in rumpf
    assert "München" in rumpf
    assert "ß" in betreff
    assert "Größe" in betreff
    assert "Größe" in rumpf
    assert "Grüße" in rumpf


def test_testinstanz_vorsatz_bleibt_bei_hinterlegtem_betreff(pg_session, tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "installation_mode", "testinstanz")
    monkeypatch.setattr(get_settings(), "testinstanz_mail_to", "test@postbox.de")
    firma_setzen(pg_session)
    cfg = config_setzen(pg_session, mail_betreff_de="Eigener {rechnungsnummer}")
    inv = rechnung_anlegen(pg_session, nummer="RE-TI-1")
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    inhalt = mailtext.rechnungsmail(inv, firma, cfg)
    pdf = tmp_path / "re.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    server = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = server
    with patch.object(
        datev_email,
        "_get_effective_smtp_config",
        return_value=SimpleNamespace(
            smtp_host="smtp.test",
            smtp_port=587,
            smtp_user="u",
            smtp_password="p",
            smtp_from="rechnung@kanzlei.de",
            smtp_use_tls=True,
            datev_bcc_email="",
        ),
    ), patch.object(datev_email.smtplib, "SMTP", return_value=smtp_cm):
        datev_email.send_invoice(
            "kunde@example.de", inhalt, pdf, bcc_datev=False, db=pg_session
        )
    msg = server.send_message.call_args.args[0]
    assert msg["Subject"] == "[TESTINSTANZ] Eigener RE-TI-1"
