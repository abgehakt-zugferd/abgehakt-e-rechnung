"""Der Mailtext an Kunde + Steuerberater darf keinen fest verdrahteten Absender
tragen (#99 §4.4).

Warum das kein Kosmetikproblem ist: diese Mail ist der EINZIGE Ort, an dem Text
aus unserem Code das Haus verlässt und bei einem Dritten (dem Steuerberater der
Nutzerin) ankommt. Ein hart kodierter Block benennt dort einen fremden Dritten
als datenschutzrechtlich Verantwortlichen für die Daten fremder Mandantschaft.
Der Absender kommt deshalb aus `company` (DB) — oder gar nicht.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.config import get_settings
from app.main import app
from app.services import datev_email, mailtext
from tests.mailtext_fixtures import (
    client_fuer,
    config_setzen,
    firma_setzen,
    rechnung_anlegen,
    smtp_doppel,
)

# Verboten ist hier der Name der SOFTWARE: die Mail benennt einen
# datenschutzrechtlich Verantwortlichen, und das ist die Nutzerin, nie das
# Werkzeug. (Im Quell-Repo stand hier der Name der Herstellerfirma.)
VERBOTEN = ("Abgehakt", "abgehakt")


def teardown_function():
    app.dependency_overrides.clear()


def _firma(**kw):
    werte = dict(name="Kanzlei Musterfrau", address_line1="Musterweg 3",
                 zip_code="80331", city="München")
    werte.update(kw)
    return SimpleNamespace(**werte)


def _invoice(**kw):
    werte = dict(
        invoice_number="RE-2026-001",
        document_language="de",
        gross_total=Decimal("119.00"),
        currency="EUR",
        due_date=date(2026, 6, 15),
        customer=SimpleNamespace(name="Kunde GmbH"),
    )
    werte.update(kw)
    return SimpleNamespace(**werte)


def _config_ns():
    return SimpleNamespace(
        mail_betreff_de=None,
        mail_text_de=None,
        mail_betreff_en=None,
        mail_text_en=None,
    )


def test_mailtext_nennt_die_konfigurierte_firma():
    inhalt = mailtext.rechnungsmail(_invoice(), _firma(), _config_ns())

    assert "Kanzlei Musterfrau" in inhalt.rumpf
    assert "RE-2026-001" in inhalt.rumpf
    for wort in VERBOTEN:
        assert wort not in inhalt.rumpf, f"Fremder Absender im Mailtext: {wort}"


def test_mailtext_nennt_die_firma_als_verantwortliche_mit_anschrift():
    """Die Verantwortlichen-Angabe ist der Teil mit Rechtswirkung — sie muss die
    Anschrift der Nutzerin tragen, nicht irgendeine."""
    inhalt = mailtext.rechnungsmail(_invoice(), _firma(), _config_ns())

    assert "Verantwortlich: Kanzlei Musterfrau, Musterweg 3, 80331 München" in inhalt.rumpf


def test_ohne_firma_nennt_der_mailtext_niemanden_als_verantwortlichen():
    """Lieber keine Angabe als eine falsche: ist keine Firma konfiguriert, wird
    kein Dritter benannt."""
    inhalt = mailtext.rechnungsmail(_invoice(), None, _config_ns())

    assert "Verantwortlich" not in inhalt.rumpf
    for wort in VERBOTEN:
        assert wort not in inhalt.rumpf


def test_testmail_traegt_keinen_fremden_absender():
    """Die SMTP-Testmail ging bisher unter dem Namen der Software raus."""
    body, betreff = datev_email.build_test_mail(_firma())

    for wort in VERBOTEN:
        assert wort not in body, f"Fremder Absender im Testmail-Text: {wort}"
        assert wort not in betreff, f"Fremder Absender im Testmail-Betreff: {wort}"


def test_versandroute_zieht_den_absender_aus_der_firma(pg_session):
    """HTTP-Route bis SMTP: Firma und Verantwortlichen-Fuss kommen aus der DB."""
    firma_setzen(pg_session)
    config_setzen(
        pg_session,
        smtp_host="smtp.test",
        smtp_port=587,
        smtp_from="rechnung@kanzlei.de",
        smtp_use_tls=False,
    )
    inv = rechnung_anlegen(pg_session)
    pdf = get_settings().storage_path / "pdfs" / inv.pdf_filename
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-1.4\ntrailer<<>>\n%%EOF\n")

    gesendet, smtp_cls = smtp_doppel()
    valid = {"is_valid": True, "raw": "Parsed PDF:valid\nXML:valid",
             "errors": [], "warnings": []}
    with patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=valid), \
         patch("smtplib.SMTP", smtp_cls):
        r = client_fuer(pg_session).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 303
    assert "Kanzlei Musterfrau" in gesendet["body"]
    assert "Verantwortlich: Kanzlei Musterfrau, Musterweg 3, 80331 München" in gesendet["body"]
    for wort in VERBOTEN:
        assert wort not in gesendet["body"], f"Fremder Absender in der Mail: {wort}"
