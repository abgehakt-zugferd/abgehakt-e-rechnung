"""
DATEV-Versand — Audit-#2. Bisher ungetestet: Route-Guards, datev_sent_at-Persistenz,
das 20-MB-Gate BEIM VERSAND (nicht nur im Export), BCC an DATEV, PDF-Anhang.

Zwei Ebenen:
  A) Route POST /invoices/{id}/datev-senden (pg_session + TestClient, send_invoice
     gemockt) — Status-/PDF-/E-Mail-Guards, datev_sent_at wird gesetzt (und der
     invoice_guard lässt genau dieses Metadatum an einer issued-Rechnung zu),
     EmailError → 400 ohne Timestamp.
  B) Service datev_email.send_invoice (SMTP gemockt) — 20-MB-Gate, „nicht
     konfiguriert", „PDF nicht gefunden", BCC-Adresse, Anhang ist PDF.
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import datev_email, mustang, pdfa

settings = get_settings()


def teardown_function():
    app.dependency_overrides.clear()


def _valid_mustang():
    return {"is_valid": True,
            "raw": "Parsed PDF:valid\nXML:valid\nSummary: 0 errors",
            "errors": [], "warnings": []}


# ── A) Route ────────────────────────────────────────────────────────────────

def _seed(pg_session, status="issued", pdf="RE.pdf", email="kunde@example.de"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München",
                 country="DE", email=email)
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status=status, pdf_filename=pdf)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_send_success_sets_datev_sent_at(pg_session):
    from fastapi.testclient import TestClient
    inv = _seed(pg_session, status="issued")
    app.dependency_overrides[get_db] = lambda: pg_session
    # Route-Orchestrierung (Status/E-Mail/Timestamp) — die echte E-Rechnungs-
    # Validität beweist die Mustang-Integration weiter unten; hier gemockt.
    with patch.object(datev_email, "send_invoice") as send, \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()):
        r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 303
    assert send.call_args.kwargs["bcc_datev"] is True
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at is not None      # invoice_guard lässt dieses Metadatum zu
    assert row.status == "issued"             # unverändert


@pytest.mark.parametrize("status", ["draft", "cancelled"])
def test_send_rejects_non_finalized(pg_session, status):
    from fastapi.testclient import TestClient
    inv = _seed(pg_session, status=status)
    app.dependency_overrides[get_db] = lambda: pg_session
    with patch.object(datev_email, "send_invoice") as send:
        r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 400
    send.assert_not_called()


def test_send_requires_pdf(pg_session):
    from fastapi.testclient import TestClient
    inv = _seed(pg_session, status="issued", pdf=None)
    app.dependency_overrides[get_db] = lambda: pg_session
    with patch.object(datev_email, "send_invoice") as send:
        r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 400
    send.assert_not_called()


def test_send_requires_email(pg_session):
    from fastapi.testclient import TestClient
    inv = _seed(pg_session, status="issued", email=None)
    app.dependency_overrides[get_db] = lambda: pg_session
    with patch.object(datev_email, "send_invoice") as send:
        r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 400
    send.assert_not_called()


def test_send_refuses_visual_pdf(pg_session):
    """Defense-in-depth (#98 P0.1): auch wenn — entgegen dem Fail-closed-Finalize —
    je eine issued-Rechnung mit reinem *_visual.pdf (ohne eingebettete ZUGFeRD-XML)
    existierte, darf sie NICHT an DATEV/Kunde versendet werden."""
    from fastapi.testclient import TestClient
    inv = _seed(pg_session, status="issued", pdf="RE-2026-visual_visual.pdf")
    app.dependency_overrides[get_db] = lambda: pg_session
    with patch.object(datev_email, "send_invoice") as send:
        r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 400
    send.assert_not_called()


def test_send_emailerror_returns_400_and_no_timestamp(pg_session):
    from fastapi.testclient import TestClient
    inv = _seed(pg_session, status="issued")
    app.dependency_overrides[get_db] = lambda: pg_session
    with patch.object(datev_email, "send_invoice", side_effect=datev_email.EmailError("SMTP kaputt")), \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()):
        r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 400
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at is None


# ── A2) E3: DATEV-Send verlangt echte E-Rechnungs-Validität (Mustang) ─────────
# Der Dateiname (`_visual.pdf`-Suffix) beweist nichts: ein beliebiges ReportLab-
# `RE.pdf` OHNE eingebettete ZUGFeRD-XML hätte den bisherigen Suffix-Check passiert
# und wäre versendbar gewesen. Verbindlich ist Mustang: nur ein PDF mit gültig
# eingebetteter XML (XML:valid) darf raus.

_needs_mustang = pytest.mark.skipif(
    not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar")
_needs_pipeline = pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar")


@_needs_mustang
def test_send_refuses_pdf_without_embedded_xml(pg_session):
    """E3: ein PDF ohne eingebettete ZUGFeRD-XML (bloßes ReportLab-PDF auf Platte)
    darf NICHT versendet werden — auch wenn der Dateiname kein `_visual`-Suffix
    trägt. Mustang lehnt es ab (kein XML:valid) → 400, send_invoice nie aufgerufen."""
    from fastapi.testclient import TestClient
    number = f"RE-BARE-{uuid.uuid4().hex[:6]}"
    inv = _seed(pg_session, status="issued", pdf=f"{number}.pdf")
    bare = settings.storage_path / "pdfs" / inv.pdf_filename
    bare.parent.mkdir(parents=True, exist_ok=True)
    bare.write_bytes(b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")
    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        with patch.object(datev_email, "send_invoice") as send:
            r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
        assert r.status_code == 400, r.text
        send.assert_not_called()
        pg_session.expire_all()
        row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
        assert row.datev_sent_at is None
    finally:
        bare.unlink(missing_ok=True)


def test_send_refuses_pdf_valid_pdfa_but_no_embedded_xml(pg_session):
    """E3: die `XML:valid`-Klausel hat eigene Zähne. Ein Mustang-Ergebnis mit
    is_valid=True, aber OHNE `XML:valid` (nur PDF/A-konform, keine eingebettete
    E-Rechnung) darf NICHT versendet werden — ein reiner is_valid-Check würde es
    durchlassen. Mock-Level (Mustang gepatcht), damit die Klausel unabhängig von
    einem realen PDF geprüft ist."""
    from fastapi.testclient import TestClient
    inv = _seed(pg_session, status="issued", pdf="RE-pdfa-only.pdf")
    app.dependency_overrides[get_db] = lambda: pg_session
    no_xml = {"is_valid": True, "raw": "Parsed PDF:valid\nSummary: 0 errors",
              "errors": [], "warnings": []}
    with patch.object(datev_email, "send_invoice") as send, \
         patch("app.routers.invoices.mustang.jar_available", return_value=True), \
         patch("app.routers.invoices.mustang.validate", return_value=no_xml):
        r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 400, r.text
    send.assert_not_called()
    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.id == inv.id).first()
    assert row.datev_sent_at is None


def test_send_refuses_when_mustang_unavailable(pg_session):
    """E3: ohne Mustang lässt sich die Einbettung nicht beweisen → fail-closed,
    kein Versand eines unvalidierten PDFs."""
    from fastapi.testclient import TestClient
    inv = _seed(pg_session, status="issued", pdf="RE-x.pdf")
    app.dependency_overrides[get_db] = lambda: pg_session
    with patch.object(datev_email, "send_invoice") as send, \
         patch("app.routers.invoices.mustang.jar_available", return_value=False):
        r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
    assert r.status_code == 400, r.text
    send.assert_not_called()


def _finalize_real(pg_session):
    """Seedet einen validen Draft mit Positionen und finalisiert ihn durch die
    ECHTE Pipeline (ReportLab → PDF/A-3 → Mustang combine + validate) → issued,
    reales ZUGFeRD-PDF auf Platte."""
    from fastapi.testclient import TestClient
    number = f"RE-SEND-{uuid.uuid4().hex[:6]}"
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München",
                 country="DE", email="kunde@example.de")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=number, customer_id=c.id, issue_date=date(2026, 6, 1),
                  delivery_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), tax_category="S", status="draft",
                  payment_terms="14 Tage netto")
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("1"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                             tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"))]
    pg_session.add(inv)
    pg_session.commit()
    app.dependency_overrides[get_db] = lambda: pg_session
    r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/finalisieren")
    assert r.status_code == 303, r.text
    pg_session.expire_all()
    return pg_session.get(Invoice, inv.id), number


@_needs_pipeline
def test_send_allows_real_zugferd_pdf(pg_session):
    """E3-Positivpfad: ein durch die echte Pipeline finalisiertes ZUGFeRD-PDF
    besteht die Mustang-Validierung beim Versand → 303, send_invoice aufgerufen."""
    from fastapi.testclient import TestClient
    inv, number = _finalize_real(pg_session)
    assert inv.status == "issued"
    assert inv.pdf_filename == f"{number}.pdf"
    try:
        with patch.object(datev_email, "send_invoice") as send:
            r = TestClient(app, follow_redirects=False).post(f"/invoices/{inv.id}/datev-senden")
        assert r.status_code == 303, r.text
        send.assert_called_once()
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.datev_sent_at is not None
    finally:
        (settings.storage_path / "pdfs" / f"{number}.pdf").unlink(missing_ok=True)
        (settings.storage_path / "pdfs" / f"{number}_visual.pdf").unlink(missing_ok=True)
        (settings.storage_path / "xml" / f"{number}.xml").unlink(missing_ok=True)


# ── B) Service send_invoice ─────────────────────────────────────────────────

def _cfg(**over):
    base = dict(smtp_host="smtp.example.de", smtp_port=587, smtp_from="re@example.de",
                smtp_user="u", smtp_password="p", smtp_use_tls=True,
                datev_bcc_email="datev-bcc@datev.de")
    base.update(over)
    return SimpleNamespace(**base)


def test_20mb_gate_blocks_send(tmp_path):
    big = tmp_path / "big.pdf"
    with open(big, "wb") as f:
        f.truncate(20 * 1024 * 1024 + 1)   # sparse: st_size > 20 MB ohne 20 MB zu schreiben
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_cfg()):
        with pytest.raises(datev_email.EmailError, match="20 MB"):
            datev_email.send_invoice("k@example.de", "RE-1", "Kunde", big)


def test_send_requires_smtp_configured(tmp_path):
    pdf = tmp_path / "a.pdf"; pdf.write_bytes(b"%PDF-1.4\n")
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_cfg(smtp_host="")):
        with pytest.raises(datev_email.EmailError, match="nicht konfiguriert"):
            datev_email.send_invoice("k@example.de", "RE-1", "Kunde", pdf)


def test_send_missing_pdf_raises(tmp_path):
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_cfg()):
        with pytest.raises(datev_email.EmailError, match="nicht gefunden"):
            datev_email.send_invoice("k@example.de", "RE-1", "Kunde", tmp_path / "fehlt.pdf")


def test_send_attaches_pdf_and_bccs_datev(tmp_path):
    pdf = tmp_path / "re.pdf"; pdf.write_bytes(b"%PDF-1.4\n%mini\n")
    server = MagicMock()
    smtp_cm = MagicMock()
    smtp_cm.__enter__.return_value = server
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_cfg()), \
         patch.object(datev_email.smtplib, "SMTP", return_value=smtp_cm):
        datev_email.send_invoice("k@example.de", "RE-77", "Kunde", pdf, bcc_datev=True)

    msg = server.send_message.call_args.args[0]
    assert msg["To"] == "k@example.de"
    assert msg["Bcc"] == "datev-bcc@datev.de"
    attachments = [p for p in msg.iter_attachments()]
    assert len(attachments) == 1
    assert attachments[0].get_content_type() == "application/pdf"


def test_send_without_bcc_omits_datev(tmp_path):
    pdf = tmp_path / "re.pdf"; pdf.write_bytes(b"%PDF-1.4\n")
    server = MagicMock()
    smtp_cm = MagicMock(); smtp_cm.__enter__.return_value = server
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_cfg()), \
         patch.object(datev_email.smtplib, "SMTP", return_value=smtp_cm):
        datev_email.send_invoice("k@example.de", "RE-77", "Kunde", pdf, bcc_datev=False)
    msg = server.send_message.call_args.args[0]
    assert msg["Bcc"] is None


# ── B2) CC-Empfänger (#147) ─────────────────────────────────────────────────
# Die Kopie ist bewusst CC und nicht BCC: sie ist für den Kunden sichtbar.

def test_send_setzt_cc_kopf(tmp_path):
    pdf = tmp_path / "re.pdf"; pdf.write_bytes(b"%PDF-1.4\n")
    server = MagicMock()
    smtp_cm = MagicMock(); smtp_cm.__enter__.return_value = server
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_cfg()), \
         patch.object(datev_email.smtplib, "SMTP", return_value=smtp_cm):
        datev_email.send_invoice("k@example.de", "RE-77", "Kunde", pdf,
                                 cc_email="buchhaltung@example.de")
    msg = server.send_message.call_args.args[0]
    assert msg["Cc"] == "buchhaltung@example.de"
    # Die CC-Adresse muss auch wirklich zugestellt werden: send_message leitet den
    # Cc-Kopf selbst in die Empfängerliste über — der Kopf ist hier die Wahrheit.
    assert msg["To"] == "k@example.de"


@pytest.mark.parametrize("leer", ["", "   ", None])
def test_send_ohne_cc_setzt_keinen_kopf(tmp_path, leer):
    """Ein leeres Feld im Sende-Dialog darf keinen leeren Cc-Kopf erzeugen —
    manche Mailserver weisen eine Nachricht mit leerem Cc zurück."""
    pdf = tmp_path / "re.pdf"; pdf.write_bytes(b"%PDF-1.4\n")
    server = MagicMock()
    smtp_cm = MagicMock(); smtp_cm.__enter__.return_value = server
    with patch.object(datev_email, "_get_effective_smtp_config", return_value=_cfg()), \
         patch.object(datev_email.smtplib, "SMTP", return_value=smtp_cm):
        datev_email.send_invoice("k@example.de", "RE-77", "Kunde", pdf, cc_email=leer)
    msg = server.send_message.call_args.args[0]
    assert msg["Cc"] is None
