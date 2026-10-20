"""Versand an Buchhaltung und Kunde entkoppelt (Bauschritt 5a, Entscheidung 6).

Bisher war der Versand EIN Schritt: Mail an den Kunden, Blindkopie an die
Upload-Adresse, und `invoices.datev_sent_at` war der Zeitpunkt fuer beides.
Ab hier zaehlt `datev_sent_at` nur noch fuer die Buchhaltung; der Kunde hat
den eigenen Vermerk `kunde_zugestellt_am`. Dieser Bauschritt baut zwei Wege:

- Standardversand (`datev-senden`): wie bisher, setzt ab jetzt BEIDE Vermerke.
  Ohne konfigurierte Upload-Adresse laeuft er weiter nur an den Kunden (so
  laeuft er heute schon, `send_invoice` setzt dann keine Blindkopie) und
  setzt dann nur `kunde_zugestellt_am` — die Buchhaltung hat nichts erhalten.
- Nur an die Buchhaltung (`an-buchhaltung`): Mail allein an die Upload-Adresse,
  neutrale Schablone ohne Kundenanrede (Festlegung 16), setzt nur
  `datev_sent_at`.

SMTP laeuft hier ausschliesslich ueber die Attrappe (`send_invoice` gepatcht):
Gezaehlt wird die Orchestrierung der Route, nie eine echte Verbindung.
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceSendLog
from app.services import datev_email, mailtext


def teardown_function():
    app.dependency_overrides.clear()


def _valid_mustang():
    return {"is_valid": True, "raw": "Parsed PDF:valid\nXML:valid",
            "errors": [], "warnings": []}


def _mustang_patches():
    return (patch("app.services.mustang.jar_available", return_value=True),
            patch("app.services.mustang.validate", return_value=_valid_mustang()))


def _upload_adresse(pg_session, adresse="upload@example.de"):
    """AppConfig-Zeile mit Upload-Adresse. Ohne sie gilt der .env-Wert, und der
    ist im Testlauf leer — genau der Fall „Buchhaltung nicht konfiguriert"."""
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if not cfg:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.datev_bcc_email = adresse
    pg_session.commit()
    return cfg


def _seed(pg_session, status="issued", email="kunde@example.de"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München",
                 country="DE", email=email)
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-VP-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status=status, pdf_filename="RE.pdf")
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


# ── Standardversand: beide Vermerke, ein Versand ─────────────────────────────

def test_standardversand_setzt_beide_vermerke(pg_session):
    inv = _seed(pg_session)
    _upload_adresse(pg_session)
    jar, val = _mustang_patches()
    with patch.object(datev_email, "send_invoice"), jar, val:
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")

    assert r.status_code == 303, r.text
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at is not None        # erstmals an die Buchhaltung
    assert row.kunde_zugestellt_am is not None  # erstmals beim Kunden
    # Beide Vermerke stammen aus DEMSELBEN Versand (Mail plus Blindkopie),
    # nicht aus zwei Klicks auf verschiedenen Wegen.
    assert row.datev_sent_at == row.kunde_zugestellt_am
    zeilen = _logs(pg_session, inv.id)
    assert len(zeilen) == 1
    assert zeilen[0].ziel == "kunde_und_buchhaltung"
    assert zeilen[0].datev_bcc is True
    assert zeilen[0].weg_notiz is None


def test_standardversand_ohne_upload_adresse_nur_kunde(pg_session):
    """Ohne Upload-Adresse läuft der Standardversand heute schon nur an den
    Kunden (send_invoice lässt die Blindkopie still weg). Dieses Verhalten
    bleibt; neu ist, dass die Vermerke ehrlich sagen, was fehlt: Die
    Buchhaltung hat nichts erhalten, also bleibt datev_sent_at leer."""
    inv = _seed(pg_session)
    jar, val = _mustang_patches()
    with patch.object(datev_email, "send_invoice") as send, jar, val:
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")

    assert r.status_code == 303, r.text
    assert send.call_args.kwargs["to_email"] == "kunde@example.de"
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.kunde_zugestellt_am is not None
    assert row.datev_sent_at is None
    zeilen = _logs(pg_session, inv.id)
    assert len(zeilen) == 1
    assert zeilen[0].ziel == "kunde_und_buchhaltung"
    assert zeilen[0].datev_bcc is False  # der Nachweis nennt die echte Empfängerliste
    assert zeilen[0].weg_notiz and "Upload-Adresse" in zeilen[0].weg_notiz


# ── Nur an die Buchhaltung ───────────────────────────────────────────────────

def test_an_buchhaltung_mailt_nur_die_upload_adresse(pg_session):
    inv = _seed(pg_session)
    _upload_adresse(pg_session)
    jar, val = _mustang_patches()
    with patch.object(datev_email, "send_invoice") as send, jar, val:
        r = _client(pg_session).post(f"/invoices/{inv.id}/an-buchhaltung")

    assert r.status_code == 303, r.text
    kwargs = send.call_args.kwargs
    assert kwargs["to_email"] == "upload@example.de"
    assert kwargs.get("bcc") is None  # An IST die Upload-Adresse, keine Blindkopie nötig
    inhalt = kwargs["mailinhalt"]
    assert inhalt.betreff == f"Beleg {inv.invoice_number} für die Buchhaltung"
    assert "Kunde GmbH" not in inhalt.rumpf  # neutrale Schablone, keine Kundenanrede

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at is not None
    assert row.kunde_zugestellt_am is None   # der Kunde bleibt offen
    zeilen = _logs(pg_session, inv.id)
    assert len(zeilen) == 1
    assert zeilen[0].ziel == "buchhaltung"
    assert zeilen[0].to_email == "upload@example.de"
    assert zeilen[0].cc_email is None
    assert zeilen[0].datev_bcc is False


def test_an_buchhaltung_ohne_upload_adresse_kein_500(pg_session):
    """Ohne konfigurierte Upload-Adresse kann der Weg nicht gehen — dann muss
    die Route das sagen (400), nicht der Server (500). Ein Protokolleintrag
    entstünde zu keinem Zeitpunkt, denn gesendet wurde nichts."""
    inv = _seed(pg_session)
    jar, val = _mustang_patches()
    with patch.object(datev_email, "send_invoice") as send, jar, val:
        r = _client(pg_session).post(f"/invoices/{inv.id}/an-buchhaltung")

    assert r.status_code == 400, r.text
    assert "Upload-Adresse" in r.text
    send.assert_not_called()
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at is None
    assert row.kunde_zugestellt_am is None
    assert _logs(pg_session, inv.id) == []


def test_an_buchhaltung_lehnt_entwurf_ab(pg_session):
    """Dieselben Vorprüfungen wie der Standardversand: ein Entwurf hat kein
    gültiges ZUGFeRD-PDF und geht an niemanden raus."""
    inv = _seed(pg_session, status="draft")
    _upload_adresse(pg_session)
    jar, val = _mustang_patches()
    with patch.object(datev_email, "send_invoice") as send, jar, val:
        r = _client(pg_session).post(f"/invoices/{inv.id}/an-buchhaltung")

    assert r.status_code == 400, r.text
    send.assert_not_called()
    assert _logs(pg_session, inv.id) == []


def test_an_buchhaltung_geht_auch_ohne_kundenadresse(pg_session):
    """Der Gewinn der Entkopplung: Ein Beleg ohne Kunden-E-Mail kann der
    Buchhaltung zugehen, bevor die Adresse des Kunden bekannt ist. Der
    Standardversand würde an derselben Stelle abbrechen."""
    inv = _seed(pg_session, email=None)
    _upload_adresse(pg_session)
    jar, val = _mustang_patches()
    with patch.object(datev_email, "send_invoice"), jar, val:
        r = _client(pg_session).post(f"/invoices/{inv.id}/an-buchhaltung")

    assert r.status_code == 303, r.text
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at is not None
    assert row.kunde_zugestellt_am is None


def test_zweiter_gang_an_die_buchhaltung_veraendert_den_vermerk_nicht(pg_session):
    """Erneutes Senden an die Buchhaltung ist erlaubt (etwa nach einem
    DATEV-Upload-Fehler), ändert aber den Erstvermerk nicht."""
    inv = _seed(pg_session)
    _upload_adresse(pg_session)
    jar, val = _mustang_patches()
    c = _client(pg_session)
    with patch.object(datev_email, "send_invoice"), jar, val:
        assert c.post(f"/invoices/{inv.id}/an-buchhaltung").status_code == 303
        pg_session.expire_all()
        erst = pg_session.query(Invoice).filter(Invoice.id == inv.id).first().datev_sent_at
        assert c.post(f"/invoices/{inv.id}/an-buchhaltung").status_code == 303

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at == erst
    assert len(_logs(pg_session, inv.id)) == 2


# ── Neutrale Mailschablone (Festlegung 16) ───────────────────────────────────

def _beleg(sprache="de"):
    return SimpleNamespace(
        invoice_number="RE-2026-001",
        document_language=sprache,
        gross_total=Decimal("119.00"),
        currency="EUR",
        due_date=date(2026, 6, 15),
        customer=SimpleNamespace(name="Kunde GmbH"),
    )


def _firma():
    return SimpleNamespace(name="Kanzlei Musterfrau", address_line1="Musterweg 3",
                           zip_code="80331", city="München")


def test_buchhaltungsmail_de_ohne_kundenanrede():
    inhalt = mailtext.buchhaltungsmail(_beleg(), _firma())

    assert inhalt.betreff == "Beleg RE-2026-001 für die Buchhaltung"
    assert "Sehr geehrte" not in inhalt.rumpf  # die Anrede gehört zum Kundenweg
    assert "Kunde GmbH" not in inhalt.rumpf    # nie den Kunden nennen
    assert "RE-2026-001" in inhalt.rumpf
    assert "Kanzlei Musterfrau" in inhalt.rumpf
    assert "Verantwortlich: Kanzlei Musterfrau, Musterweg 3, 80331 München" in inhalt.rumpf


def test_buchhaltungsmail_en_ohne_kundenanrede():
    inhalt = mailtext.buchhaltungsmail(_beleg("en"), _firma())

    assert inhalt.betreff == "Document RE-2026-001 for accounting"
    assert "Dear Sir" not in inhalt.rumpf
    assert "RE-2026-001" in inhalt.rumpf


# ── Detailseite ──────────────────────────────────────────────────────────────

def test_detailseite_zeigt_weg_zur_buchhaltung_nur_bei_gestellten_belegen(pg_session):
    gestellt = _seed(pg_session, status="issued")
    entwurf = _seed(pg_session, status="draft")
    _upload_adresse(pg_session)
    c = _client(pg_session)

    seite = c.get(f"/invoices/{gestellt.id}")
    assert seite.status_code == 200
    assert f"/invoices/{gestellt.id}/an-buchhaltung" in seite.text
    assert "NUR AN DIE BUCHHALTUNG" in seite.text

    seite = c.get(f"/invoices/{entwurf.id}")
    assert seite.status_code == 200
    assert "/an-buchhaltung" not in seite.text
