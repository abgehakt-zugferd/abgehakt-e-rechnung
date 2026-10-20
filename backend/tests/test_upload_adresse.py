"""Upload-Adresse: Leerzeichen gelten ueberall als nicht gesetzt (#176).

Eine Stelle trimmt (`upload_adresse`), Leser ohne diese Quelle behandeln
Leerzeichen als gesetzt. EmailMessage liefert einen Leerzeichen-Bcc-Header
beim Lesen als '' zurueck — Zusicherung daher auf das Setzen, nicht den Lesewert.
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import datev_email
from tests.mailtext_fixtures import smtp_doppel


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


def _kunde(pg_session):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Probe Kunde",
        address_line1="Weg 1", zip_code="80331", city="Muenchen",
        country="DE", email="kunde@example.test",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _rechnung(pg_session, *, status="issued", pdf="RE.pdf"):
    c = _kunde(pg_session)
    netto, steuer = Decimal("100.00"), Decimal("19.00")
    inv = Invoice(
        invoice_number=f"RE-UA-{uuid.uuid4().hex[:6]}",
        customer_id=c.id, issue_date=date(2026, 9, 1),
        due_date=date(2026, 9, 28), currency="EUR",
        net_total=netto, tax_total=steuer, gross_total=netto + steuer,
        status=status, pdf_filename=pdf, zugferd_profile="EN16931",
        tax_category="S",
    )
    inv.items = [InvoiceItem(
        position=1, description="Beratung", unit="Stunde", quantity=Decimal("1"),
        unit_price=netto, tax_rate=Decimal("19"), net_amount=netto,
        tax_amount=steuer, gross_amount=netto + steuer,
    )]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _mustang_voll_gueltig():
    return {
        "is_valid": True, "raw": "Parsed PDF:valid\nXML:valid",
        "errors": [], "warnings": [],
    }


def test_leerzeichen_upload_adresse_ohne_blindkopie(pg_session):
    """Effektive Upload-Adresse leer (nur Leerzeichen) → kein Buchhaltungs-Vermerk
    und keine Blindkopie aus Leerzeichen. SMTP ist Systemgrenze; Zusicherung auf
    den an die Nachricht uebergebenen Bcc-Wert (vor Header-Normalisierung)."""
    from email.message import EmailMessage

    _config(pg_session, datev_bcc_email="   ")
    assert datev_email.upload_adresse(pg_session) is None

    inv = _rechnung(pg_session, status="issued", pdf="RE-UA-UP.pdf")
    ziel = get_settings().storage_path / "pdfs" / inv.pdf_filename
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_bytes(b"%PDF-probe\n")

    mock_cfg = SimpleNamespace(
        smtp_host="smtp.example.test", smtp_port=587,
        smtp_from="absender@example.test", smtp_user="u", smtp_password="p",
        smtp_use_tls=True, datev_bcc_email="   ",
    )
    gesetzte_bcc: list[str] = []
    original_setitem = EmailMessage.__setitem__

    def _bcc_beobachten(self, key, value):
        if str(key).lower() == "bcc":
            gesetzte_bcc.append(value)
        return original_setitem(self, key, value)

    gesendet, smtp = smtp_doppel()
    with patch.object(EmailMessage, "__setitem__", _bcc_beobachten), \
         patch.object(datev_email, "_get_effective_smtp_config", return_value=mock_cfg), \
         patch.object(datev_email.smtplib, "SMTP", smtp), \
         patch("app.services.mustang.jar_available", return_value=True), \
         patch("app.services.mustang.validate", return_value=_mustang_voll_gueltig()):
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")

    assert r.status_code == 303, r.text
    pg_session.expire_all()
    row = pg_session.get(Invoice, inv.id)
    assert row.datev_sent_at is None
    assert "msg" in gesendet, "Versand muss die Mail wirklich absetzen"
    assert gesetzte_bcc == [], f"keine Blindkopie erwartet, gesetzt: {gesetzte_bcc!r}"


def test_detailseite_leerzeichen_upload_adresse_nicht_aktiv(pg_session):
    """Leerzeichen-Upload-Adresse: Detailseite zeigt die Weitergabe nicht als aktiv."""
    inv = _rechnung(pg_session, status="issued")
    _config(pg_session, smtp_host="smtp.example.test", datev_bcc_email="   ")

    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert r.status_code == 200
    assert "BCC → DATEV UPLOAD MAIL" not in r.text
    assert "BCC DATEV Upload Mail" not in r.text
    assert "NUR AN DIE BUCHHALTUNG" not in r.text
    assert "+ DATEV" not in r.text
