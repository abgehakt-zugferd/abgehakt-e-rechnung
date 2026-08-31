"""Mehrere Adressen in Kopie, je Kunde hinterlegbar (#58).

Vier Ebenen, weil die Liste durch vier Hände geht: der Kundenstamm hält sie, die
Einstellungen halten eine globale Voreinstellung, die Detailseite belegt das Feld
mit der einen ODER der anderen vor, und der Sende-Router schickt das ab, was im
Formular steht. Der Nachweis darüber steht im Versandprotokoll.

Die Vorbelegung ist ausdrücklich eine Vorrangkette und keine Vereinigung: würden
Kundenliste und globale Voreinstellung zusammengeworfen, ließe sich die globale
Adresse bei einem einzelnen Kunden nie mehr abwählen.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceSendLog
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


def _kundendaten(**abweichung):
    daten = {"name": "Kunde GmbH", "address_line1": "Weg 1", "zip_code": "80331",
             "city": "München", "country": "DE", "email": "kunde@example.de"}
    daten.update(abweichung)
    return daten


def _seed_issued(pg_session, cc_emails=None):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", cc_emails=cc_emails,
                 **_kundendaten())
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-CC58-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status="issued", pdf_filename="RE.pdf")
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _mustang_gruen():
    return {"is_valid": True, "raw": "Parsed PDF:valid\nXML:valid", "errors": [], "warnings": []}


def _sende(pg_session, invoice, **formulardaten):
    with patch.object(datev_email, "send_invoice") as send, \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_mustang_gruen()):
        antwort = _client(pg_session).post(
            f"/invoices/{invoice.id}/datev-senden", data=formulardaten)
    return antwort, send


# ── Kundenstamm ─────────────────────────────────────────────────────────────

def test_kundenformular_speichert_mehrere_cc_adressen(pg_session):
    r = _client(pg_session).post("/customers/neu", data=_kundendaten(
        cc_emails=" ines@example.de ; buchhaltung@example.de "))
    assert r.status_code == 303
    kunde = pg_session.query(Customer).filter(Customer.name == "Kunde GmbH").one()
    assert kunde.cc_emails == "ines@example.de, buchhaltung@example.de"


def test_kundenformular_weist_ungueltige_cc_adresse_ab(pg_session):
    r = _client(pg_session).post("/customers/neu", data=_kundendaten(
        cc_emails="ines@example.de, ohne-at-zeichen"))
    assert r.status_code == 200
    assert "ohne-at-zeichen" in r.text
    assert pg_session.query(Customer).count() == 0


def test_leeres_kundenfeld_wird_zu_null(pg_session):
    """Leer heißt „nichts hinterlegt" und muss deshalb auf die Voreinstellung
    zurückfallen können. Der leere String täte das nicht."""
    r = _client(pg_session).post("/customers/neu", data=_kundendaten(cc_emails="  "))
    assert r.status_code == 303
    assert pg_session.query(Customer).one().cc_emails is None


# ── Vorbelegung auf der Detailseite ─────────────────────────────────────────

def test_detailseite_nimmt_die_liste_aus_dem_kundenstamm(pg_session):
    inv = _seed_issued(pg_session, cc_emails="ines@example.de, buchhaltung@example.de")
    _config(pg_session, smtp_host="smtp.example.de", datev_bcc_email="datev@example.de",
            invoice_cc_email="ablage@example.de")
    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert r.status_code == 200
    assert 'value="ines@example.de, buchhaltung@example.de"' in r.text
    assert "ablage@example.de" not in r.text
    assert "Aus dem Kundenstamm" in r.text


def test_detailseite_faellt_ohne_kundenliste_auf_die_voreinstellung_zurueck(pg_session):
    inv = _seed_issued(pg_session, cc_emails=None)
    _config(pg_session, smtp_host="smtp.example.de", datev_bcc_email="datev@example.de",
            invoice_cc_email="ablage@example.de")
    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert 'value="ablage@example.de"' in r.text
    assert "Aus den Einstellungen" in r.text


def test_detailseite_nimmt_im_cc_feld_mehrere_adressen_an(pg_session):
    """Ohne `multiple` weist schon der Browser eine Liste ab, und der Server
    bekäme die zweite Adresse nie zu sehen."""
    inv = _seed_issued(pg_session)
    _config(pg_session, smtp_host="smtp.example.de", datev_bcc_email="datev@example.de")
    r = _client(pg_session).get(f"/invoices/{inv.id}")
    feld = r.text[r.text.index('name="cc_email"') - 200:r.text.index('name="cc_email"') + 200]
    assert "multiple" in feld


# ── Versand ─────────────────────────────────────────────────────────────────

def test_versand_reicht_mehrere_cc_adressen_durch(pg_session):
    inv = _seed_issued(pg_session)
    r, send = _sende(pg_session, inv,
                     cc_email="ines@example.de; buchhaltung@example.de")
    assert r.status_code == 303
    assert send.call_args.kwargs["cc_email"] == "ines@example.de, buchhaltung@example.de"


def test_versand_streicht_den_empfaenger_aus_der_kopie(pg_session):
    """Sonst bekommt der Adressat dieselbe Rechnung zweimal."""
    inv = _seed_issued(pg_session)
    r, send = _sende(pg_session, inv, cc_email="Kunde@example.de, ines@example.de")
    assert r.status_code == 303
    assert send.call_args.kwargs["cc_email"] == "ines@example.de"


def test_versand_bricht_bei_ungueltiger_adresse_ab_und_protokolliert_nichts(pg_session):
    """Die Prüfung gehört vor `db.add(protokoll)`: eine abgelehnte Eingabe hat nie
    gesendet und darf keine Protokollzeile mit offenem Ausgang hinterlassen."""
    inv = _seed_issued(pg_session)
    r, send = _sende(pg_session, inv, cc_email="ines@example.de, ohne-at-zeichen")
    assert r.status_code == 400
    assert send.call_count == 0
    assert pg_session.query(InvoiceSendLog).count() == 0


def test_protokoll_haelt_die_tatsaechlich_verwendete_liste(pg_session):
    inv = _seed_issued(pg_session, cc_emails="stammdaten@example.de")
    r, _ = _sende(pg_session, inv, cc_email="ines@example.de, buchhaltung@example.de")
    assert r.status_code == 303
    pg_session.expire_all()
    protokoll = pg_session.query(InvoiceSendLog).one()
    assert protokoll.cc_email == "ines@example.de, buchhaltung@example.de"


# ── Einstellungen ───────────────────────────────────────────────────────────

def test_einstellungen_speichern_mehrere_adressen(pg_session):
    r = _client(pg_session).post("/settings/datev", data={
        "datev_bcc_email": "datev@example.de",
        "invoice_cc_email": "ablage@example.de;archiv@example.de"})
    assert r.status_code == 303
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.invoice_cc_email == "ablage@example.de, archiv@example.de"


def test_einstellungen_weisen_ungueltige_adresse_ab(pg_session):
    _config(pg_session, invoice_cc_email="ablage@example.de")
    r = _client(pg_session).post("/settings/datev", data={
        "datev_bcc_email": "datev@example.de", "invoice_cc_email": "ohne-at-zeichen"})
    assert r.status_code == 303
    assert "error=" in r.headers["location"]
    pg_session.expire_all()
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert cfg.invoice_cc_email == "ablage@example.de"


# ── Mailkopf ────────────────────────────────────────────────────────────────

def test_cc_kopf_traegt_beide_adressen(tmp_path):
    """Der Kopf ist die Wahrheit: `send_message` leitet Cc selbst in die
    Empfängerliste über. Steht dort nur eine Adresse, bekommt die zweite Person
    nichts, ohne dass irgendwo ein Fehler entsteht."""
    pdf = tmp_path / "re.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    cfg = type("Cfg", (), {"smtp_host": "smtp.example.de", "smtp_port": 587,
                           "smtp_user": "u", "smtp_password": "p",
                           "smtp_from": "rechnung@example.de", "smtp_use_tls": True,
                           "datev_bcc_email": "datev@example.de"})()
    server = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = server
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=cfg), \
         patch.object(datev_email.smtplib, "SMTP", return_value=smtp_cm):
        datev_email.send_invoice("kunde@example.de", "RE-77", "Kunde", pdf,
                                 cc_email="ines@example.de, buchhaltung@example.de")
    msg = server.send_message.call_args.args[0]
    assert msg["Cc"] == "ines@example.de, buchhaltung@example.de"
