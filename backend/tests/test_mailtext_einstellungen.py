"""Mailtext in den Einstellungen: Speichern, leeren, Platzhalter, UI."""
from pathlib import Path

from app.main import app
from app.models.app_config import AppConfig
from app.models.company import Company
from app.services import mailtext
from tests.mailtext_fixtures import (
    client_fuer,
    config_setzen,
    firma_setzen,
    rechnung_anlegen,
)


def teardown_function():
    app.dependency_overrides.clear()


def test_ohne_hinterlegten_text_ist_deutscher_rumpf_zeichengleich(pg_session):
    """Vergleichstext ausgeschrieben, nicht ueber die gepruefte Funktion."""
    firma_setzen(pg_session)
    inv = rechnung_anlegen(pg_session, nummer="RE-2026-001")
    cfg = config_setzen(pg_session)
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
    firma_setzen(pg_session)
    cfg = config_setzen(
        pg_session,
        mail_betreff_de="DE-Betreff {rechnungsnummer}",
        mail_text_de="Deutscher Rumpf {rechnungsnummer}",
        mail_betreff_en="EN-Betreff {rechnungsnummer}",
        mail_text_en="English body {rechnungsnummer}",
    )
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    de = mailtext.rechnungsmail(
        rechnung_anlegen(pg_session, document_language="de", nummer="RE-DE-1"),
        firma,
        cfg,
    )
    en = mailtext.rechnungsmail(
        rechnung_anlegen(pg_session, document_language="en", nummer="RE-EN-1"),
        firma,
        cfg,
    )
    assert de.betreff == "DE-Betreff RE-DE-1"
    assert "Deutscher Rumpf RE-DE-1" in de.rumpf
    assert en.betreff == "EN-Betreff RE-EN-1"
    assert "English body RE-EN-1" in en.rumpf
    assert "Deutscher Rumpf" not in en.rumpf


def test_feld_leeren_stellt_eingebauten_text_wieder_her(pg_session):
    firma_setzen(pg_session)
    config_setzen(pg_session, mail_text_de="Eigener Text {rechnungsnummer}")
    r = client_fuer(pg_session).post(
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
    inhalt = mailtext.rechnungsmail(
        rechnung_anlegen(pg_session, nummer="RE-2026-009"), firma, cfg
    )
    assert "Sehr geehrte Damen und Herren," in inhalt.rumpf
    assert "Eigener Text" not in inhalt.rumpf


def test_unbekannter_platzhalter_beim_speichern_abgelehnt(pg_session):
    config_setzen(pg_session, mail_text_de="Alt {rechnungsnummer}")
    r = client_fuer(pg_session).post(
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
    assert "Hallo {unbekannt}" in r.text
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.mail_text_de == "Alt {rechnungsnummer}"


def test_betreff_folgt_belegsprache(pg_session):
    firma_setzen(pg_session)
    cfg = config_setzen(
        pg_session,
        mail_betreff_de="Rechnung DE {rechnungsnummer}",
        mail_betreff_en="Invoice EN {rechnungsnummer}",
    )
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    de = mailtext.rechnungsmail(
        rechnung_anlegen(pg_session, document_language="de", nummer="N1"), firma, cfg
    )
    en = mailtext.rechnungsmail(
        rechnung_anlegen(pg_session, document_language="en", nummer="N2"), firma, cfg
    )
    assert de.betreff == "Rechnung DE N1"
    assert en.betreff == "Invoice EN N2"


def test_einstellungsseite_zeigt_mailtext_abschnitt(pg_session):
    r = client_fuer(pg_session).get("/settings/")
    assert r.status_code == 200
    assert "Text der Rechnungsmail" in r.text
    assert 'name="mail_betreff_de"' in r.text
    assert 'name="mail_text_en"' in r.text
    for name in mailtext.PLATZHALTER:
        assert "{" + name + "}" in r.text


def test_kein_str_format_kein_jinja_in_mailtext_modul():
    quell = Path(mailtext.__file__).read_text(encoding="utf-8")
    ohne_kommentar = "\n".join(
        zeile for zeile in quell.splitlines() if not zeile.lstrip().startswith("#")
    )
    assert ".format(" not in ohne_kommentar
    assert "jinja" not in ohne_kommentar.lower()
    assert "str.format" not in ohne_kommentar
