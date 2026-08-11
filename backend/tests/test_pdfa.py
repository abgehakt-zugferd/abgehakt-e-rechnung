"""Tests für services/pdfa.py — Ghostscript PDF/A-3-Konvertierung.

Voraussetzung für Mustangs combine: der Eingabe-PDF muss ein PDF/A sein
(ZUGFeRDExporterFromPDFA liest pdfaid:part aus dem XMP). ReportLab erzeugt
ein normales PDF; Ghostscript hebt es auf PDF/A-3 (XMP + sRGB OutputIntent)."""
from datetime import date
from decimal import Decimal

import pytest

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, pdf_generator, pdfa


def _company():
    return Company(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", email="info@example.de", phone="+49 111",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE00123456780000000000", bank_bic="ABCDDEFF", bank_name="Testbank",
        country="DE",
    )


def _invoice():
    cust = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                    zip_code="10115", city="Berlin", country="DE")
    item = InvoiceItem(position=1, description="Beratungsleistung", quantity=Decimal("2"),
                       unit="Std", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
                       net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"))
    inv = Invoice(invoice_number="RE-2026-779", issue_date=date(2026, 7, 8),
                  delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22),
                  currency="EUR", net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"), tax_category="S",
                  payment_terms="Zahlbar innerhalb 14 Tagen.", notes="")
    inv.customer = cust
    inv.items = [item]
    return inv


def test_to_pdfa3_missing_input_returns_false(tmp_path):
    """Fehlt die Eingabedatei, meldet to_pdfa3 sauber Fehlschlag (kein Crash)."""
    if not pdfa.gs_available():
        pytest.skip("Ghostscript nicht verfügbar")
    out = tmp_path / "out.pdf"
    assert pdfa.to_pdfa3(tmp_path / "does-not-exist.pdf", out) is False
    assert not out.exists()


@pytest.mark.skipif(not pdfa.gs_available(), reason="Ghostscript nicht verfügbar")
def test_to_pdfa3_produces_pdfa(tmp_path):
    src = tmp_path / "src.pdf"
    pdf_generator.generate_pdf(_invoice(), _company(), src)

    out = tmp_path / "out.pdf"
    assert pdfa.to_pdfa3(src, out, title="RE-2026-779") is True
    assert out.exists() and out.stat().st_size > 0


@pytest.mark.skipif(
    not (pdfa.gs_available() and mustang.jar_available()),
    reason="Ghostscript oder Mustang-JAR nicht verfügbar",
)
def test_to_pdfa3_output_is_valid_pdfa_per_mustang(tmp_path):
    src = tmp_path / "src.pdf"
    pdf_generator.generate_pdf(_invoice(), _company(), src)
    out = tmp_path / "out.pdf"
    assert pdfa.to_pdfa3(src, out, title="RE-2026-779") is True

    # Ohne eingebettete ZUGFeRD-XML meldet Mustang die reine PDF/A-Prüfung im
    # <pdf>-Block. isCompliant=true bestätigt: das gs-Ausgabe-PDF ist gültiges
    # PDF/A (flavour=3b). Die volle ZUGFeRD-Validierung deckt der Integrationstest ab.
    raw = mustang.validate(out)["raw"]
    assert "isCompliant=true" in raw, raw


def test_ps_escape_strips_control_chars_and_escapes_specials():
    from app.services.pdfa import _ps_escape
    out = _ps_escape("RE-2026\n(001)\\x")
    assert "\n" not in out and "\r" not in out
    assert "\\(" in out and "\\)" in out
    assert "\\\\" in out  # Backslash maskiert


def test_to_pdfa3_meldet_die_zeitgrenze_als_fehlschlag_statt_zu_werfen(tmp_path):
    """Ghostscript steht im Finalisieren direkt vor Mustang und hat dieselbe
    Zeitgrenze (120 s). Eine durchfliegende `TimeoutExpired` umginge auch hier das
    Aufraeumen und den Rollback — sie gehoert in ein False, das der fail-closed-Weg
    ohnehin behandelt."""
    import subprocess
    from unittest.mock import patch

    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-1.4")

    def _zeitgrenze(*a, **k):
        raise subprocess.TimeoutExpired(cmd="gs", timeout=120)

    with patch("app.services.pdfa.subprocess.run", side_effect=_zeitgrenze):
        assert pdfa.to_pdfa3(src, tmp_path / "out.pdf", title="RE-TEST") is False
