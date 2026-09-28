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

from app.models.app_config import AppConfig
from app.models.company import Company
from app.services import datev_email, mailtext

# Verboten ist hier der Name der SOFTWARE: die Mail benennt einen
# datenschutzrechtlich Verantwortlichen, und das ist die Nutzerin, nie das
# Werkzeug. (Im Quell-Repo stand hier der Name der Herstellerfirma.)
VERBOTEN = ("Abgehakt", "abgehakt")


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


def _config():
    return SimpleNamespace(
        mail_betreff_de=None,
        mail_text_de=None,
        mail_betreff_en=None,
        mail_text_en=None,
    )


def test_mailtext_nennt_die_konfigurierte_firma():
    inhalt = mailtext.rechnungsmail(_invoice(), _firma(), _config())

    assert "Kanzlei Musterfrau" in inhalt.rumpf
    assert "RE-2026-001" in inhalt.rumpf
    for wort in VERBOTEN:
        assert wort not in inhalt.rumpf, f"Fremder Absender im Mailtext: {wort}"


def test_mailtext_nennt_die_firma_als_verantwortliche_mit_anschrift():
    """Die Verantwortlichen-Angabe ist der Teil mit Rechtswirkung — sie muss die
    Anschrift der Nutzerin tragen, nicht irgendeine."""
    inhalt = mailtext.rechnungsmail(_invoice(), _firma(), _config())

    assert "Verantwortlich: Kanzlei Musterfrau, Musterweg 3, 80331 München" in inhalt.rumpf


def test_ohne_firma_nennt_der_mailtext_niemanden_als_verantwortlichen():
    """Lieber keine Angabe als eine falsche: ist keine Firma konfiguriert, wird
    kein Dritter benannt."""
    inhalt = mailtext.rechnungsmail(_invoice(), None, _config())

    assert "Verantwortlich" not in inhalt.rumpf
    for wort in VERBOTEN:
        assert wort not in inhalt.rumpf


def test_testmail_traegt_keinen_fremden_absender():
    """Die SMTP-Testmail ging bisher unter dem Namen der Software raus."""
    body, betreff = datev_email.build_test_mail(_firma())

    for wort in VERBOTEN:
        assert wort not in body, f"Fremder Absender im Testmail-Text: {wort}"
        assert wort not in betreff, f"Fremder Absender im Testmail-Betreff: {wort}"


def test_send_invoice_zieht_den_absender_aus_der_datenbank(pg_session, tmp_path):
    """Integration: der Versandweg selbst (nicht nur der Textbaustein) benutzt die
    Firma aus der DB. Break-and-Revert-fest — ein wieder hart kodierter Absender
    fällt hier auf, auch wenn rechnungsmail korrekt bleibt."""
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    firma.name = "Kanzlei Musterfrau"
    firma.address_line1 = "Musterweg 3"
    firma.zip_code = "80331"
    firma.city = "München"
    pg_session.commit()

    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if not cfg:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
        pg_session.commit()

    inhalt = mailtext.rechnungsmail(
        SimpleNamespace(
            invoice_number="RE-2026-001",
            document_language="de",
            gross_total=Decimal("119.00"),
            currency="EUR",
            due_date=date(2026, 6, 15),
            customer=SimpleNamespace(name="Kunde GmbH"),
        ),
        firma,
        cfg,
    )

    pdf = tmp_path / "RE-2026-001.pdf"
    pdf.write_bytes(b"%PDF-1.4\ntrailer<<>>\n%%EOF\n")

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

    with patch.object(datev_email, "_get_effective_smtp_config",
                      return_value=SimpleNamespace(
                          smtp_host="smtp.test", smtp_port=587, smtp_user="",
                          smtp_password="", smtp_from="rechnung@kanzlei.de",
                          smtp_use_tls=False, datev_bcc_email="")), \
         patch("smtplib.SMTP", _SMTP):
        datev_email.send_invoice("kunde@example.de", inhalt, pdf,
                                 bcc_datev=False, db=pg_session)

    assert "Kanzlei Musterfrau" in gesendet["body"]
    for wort in VERBOTEN:
        assert wort not in gesendet["body"], f"Fremder Absender in der Mail: {wort}"
