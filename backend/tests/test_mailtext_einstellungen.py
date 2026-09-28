"""Mailtext in Einstellungen und Versand: Integration mit pg_session.

docs/specs/mailtext.md — Speichern, Sprachwahl aus document_language, SMTP-Doppel.
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services import datev_email, mailtext


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


def _firma(pg_session, **kw):
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    werte = dict(
        name="Kanzlei Musterfrau",
        address_line1="Musterweg 3",
        zip_code="80331",
        city="München",
    )
    werte.update(kw)
    for k, v in werte.items():
        setattr(firma, k, v)
    pg_session.commit()
    return firma


def _rechnung(pg_session, *, document_language="de", nummer=None):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Kunde GmbH",
        address_line1="Weg 1",
        zip_code="80331",
        city="München",
        country="DE",
        email="kunde@example.de",
    )
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(
        invoice_number=nummer or f"RE-MT-{uuid.uuid4().hex[:6]}",
        customer_id=c.id,
        issue_date=date(2026, 9, 1),
        due_date=date(2026, 9, 28),
        currency="EUR",
        net_total=Decimal("1000.00"),
        tax_total=Decimal("234.56"),
        gross_total=Decimal("1234.56"),
        status="issued",
        pdf_filename="RE.pdf",
        document_language=document_language,
    )
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    return inv


def test_ohne_hinterlegten_text_ist_deutscher_rumpf_zeichengleich(pg_session):
    """Vergleichstext ausgeschrieben, nicht ueber die gepruefte Funktion."""
    _firma(pg_session)
    inv = _rechnung(pg_session, nummer="RE-2026-001")
    cfg = _config(pg_session)
    erwartet = (
        "Sehr geehrte Damen und Herren,\n"
        "\n"
        "anbei erhalten Sie Ihre Rechnung RE-2026-001.\n"
        "\n"
        "Das Dokument enthält die strukturierten ZUGFeRD-Rechnungsdaten "
        "(Factur-X EN16931) gemäß § 14 UStG.\n"
        "\n"
        "Bei Fragen stehen wir Ihnen gerne zur Verfügung.\n"
        "\n"
        "Mit freundlichen Grüßen\n"
        "Kanzlei Musterfrau\n"
        "\n"
        "---\n"
        "Verantwortlich: Kanzlei Musterfrau, Musterweg 3, 80331 München\n"
    )
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    inhalt = mailtext.rechnungsmail(inv, firma, cfg)
    assert inhalt.rumpf == erwartet
    assert inhalt.betreff == "Rechnung RE-2026-001"


def test_deutscher_text_wirkt_nicht_auf_englischen_beleg(pg_session):
    _firma(pg_session)
    cfg = _config(
        pg_session,
        mail_betreff_de="DE-Betreff {rechnungsnummer}",
        mail_text_de="Deutscher Rumpf {rechnungsnummer}",
        mail_betreff_en="EN-Betreff {rechnungsnummer}",
        mail_text_en="English body {rechnungsnummer}",
    )
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    de = mailtext.rechnungsmail(
        _rechnung(pg_session, document_language="de", nummer="RE-DE-1"),
        firma,
        cfg,
    )
    en = mailtext.rechnungsmail(
        _rechnung(pg_session, document_language="en", nummer="RE-EN-1"),
        firma,
        cfg,
    )
    assert de.betreff == "DE-Betreff RE-DE-1"
    assert "Deutscher Rumpf RE-DE-1" in de.rumpf
    assert de.betreff != en.betreff
    assert en.betreff == "EN-Betreff RE-EN-1"
    assert "English body RE-EN-1" in en.rumpf
    assert "Deutscher Rumpf" not in en.rumpf


def test_feld_leeren_stellt_eingebauten_text_wieder_her(pg_session):
    _firma(pg_session)
    _config(pg_session, mail_text_de="Eigener Text {rechnungsnummer}")
    client = _client(pg_session)
    r = client.post(
        "/settings/mailtext",
        data={
            "mail_betreff_de": "",
            "mail_text_de": "",
            "mail_betreff_en": "",
            "mail_text_en": "",
        },
    )
    assert r.status_code == 303
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.mail_text_de is None
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    inv = _rechnung(pg_session, nummer="RE-2026-009")
    inhalt = mailtext.rechnungsmail(inv, firma, cfg)
    assert "Sehr geehrte Damen und Herren," in inhalt.rumpf
    assert "Eigener Text" not in inhalt.rumpf


def test_unbekannter_platzhalter_beim_speichern_abgelehnt(pg_session):
    _config(pg_session, mail_text_de="Alt {rechnungsnummer}")
    client = _client(pg_session)
    r = client.post(
        "/settings/mailtext",
        data={
            "mail_betreff_de": "Rechnung {rechnungsnummer}",
            "mail_text_de": "Hallo {unbekannt}",
            "mail_betreff_en": "",
            "mail_text_en": "",
        },
    )
    assert r.status_code == 200
    assert "unbekannt" in r.text
    assert 'name="mail_text_de"' in r.text
    assert "Hallo {unbekannt}" in r.text
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.mail_text_de == "Alt {rechnungsnummer}"


def test_umlaute_und_eszett_ueberleben_speichern_lesen_versand(pg_session, tmp_path):
    _firma(pg_session, name="Büro Größe")
    text = "Grüße aus München für die Größe {rechnungsnummer}"
    client = _client(pg_session)
    r = client.post(
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

    inv = _rechnung(pg_session, nummer="RE-Ü-1")
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    inhalt = mailtext.rechnungsmail(inv, firma, cfg)
    assert "Grüße aus München für die Größe RE-Ü-1" in inhalt.rumpf

    pdf = tmp_path / "re.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    gesendet = {}

    class _SMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, **k):
            pass

        def login(self, *a):
            pass

        def send_message(self, msg):
            gesendet["body"] = msg.get_body(preferencelist=("plain",)).get_content()
            gesendet["subject"] = msg["Subject"]

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
    ), patch("smtplib.SMTP", _SMTP):
        datev_email.send_invoice(
            "kunde@example.de",
            inhalt,
            pdf,
            bcc_datev=False,
            db=pg_session,
        )
    assert "Grüße aus München für die Größe RE-Ü-1" in gesendet["body"]
    assert "Größe" in gesendet["subject"]


def test_betreff_folgt_belegsprache(pg_session):
    _firma(pg_session)
    cfg = _config(
        pg_session,
        mail_betreff_de="Rechnung DE {rechnungsnummer}",
        mail_betreff_en="Invoice EN {rechnungsnummer}",
    )
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    de = mailtext.rechnungsmail(
        _rechnung(pg_session, document_language="de", nummer="N1"), firma, cfg
    )
    en = mailtext.rechnungsmail(
        _rechnung(pg_session, document_language="en", nummer="N2"), firma, cfg
    )
    assert de.betreff == "Rechnung DE N1"
    assert en.betreff == "Invoice EN N2"


def test_testinstanz_vorsatz_bleibt_bei_hinterlegtem_betreff(pg_session, tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "installation_mode", "testinstanz")
    monkeypatch.setattr(get_settings(), "testinstanz_mail_to", "test@postbox.de")
    _firma(pg_session)
    cfg = _config(pg_session, mail_betreff_de="Eigener {rechnungsnummer}")
    inv = _rechnung(pg_session, nummer="RE-TI-1")
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


def test_einstellungsseite_zeigt_mailtext_abschnitt(pg_session):
    r = _client(pg_session).get("/settings/")
    assert r.status_code == 200
    assert "Text der Rechnungsmail" in r.text
    assert 'name="mail_betreff_de"' in r.text
    assert 'name="mail_text_en"' in r.text
    for name in mailtext.PLATZHALTER:
        assert "{" + name + "}" in r.text


def test_kein_str_format_kein_jinja_in_mailtext_modul():
    """Architektur-Lint: Ersetzen nur ueber den engen Ausdruck."""
    from pathlib import Path

    quell = Path(mailtext.__file__).read_text(encoding="utf-8")
    ohne_kommentar = "\n".join(
        zeile for zeile in quell.splitlines() if not zeile.lstrip().startswith("#")
    )
    assert ".format(" not in ohne_kommentar
    assert "jinja" not in ohne_kommentar.lower()
    assert "str.format" not in ohne_kommentar
