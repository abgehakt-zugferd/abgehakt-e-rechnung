"""
Tests für mustang._no_errors().
Bug: substring-Suche nach "error" trifft auch "0 errors" in Erfolgsmeldungen.
"""
from app.services.mustang import _no_errors


def test_empty_output_has_no_errors():
    assert _no_errors("") is True


def test_clean_success_message_has_no_errors():
    assert _no_errors("Factur-X validation passed successfully.") is True


def test_zero_errors_count_in_summary_is_not_an_error():
    # Regression: Mustang gibt bei Erfolg "0 error(s)" aus — das darf nicht
    # als Fehlerindikator gelten.
    assert _no_errors("Validation of invoice.xml: 0 error(s), 0 warning(s)") is True


def test_zero_errors_alternative_phrasing():
    assert _no_errors("Summary: 0 errors found, 0 warnings found") is True


def test_bracketed_error_is_detected():
    assert _no_errors("[ERROR] BT-2 IssueDateTime is required") is False


def test_lowercase_bracketed_error_is_detected():
    assert _no_errors("[error] Missing mandatory field SellerName") is False


def test_german_fehler_in_brackets_is_detected():
    assert _no_errors("[Fehler] Pflichtfeld fehlt: Rechnungsnummer") is False


def test_mixed_valid_output_with_error_line():
    output = "Checking invoice.xml\n[error] BT-31 is required\n0 warnings"
    assert _no_errors(output) is False


# --- combine() Härtung: non-interaktiv + echte Erfolgsprüfung ---
from pathlib import Path
from app.services import mustang


def test_combine_false_when_output_not_written(monkeypatch, tmp_path):
    """Regression: Mustang wirft bei fehlendem stdin eine NPE, schreibt KEINE
    Datei, exitet aber rc=0. combine() muss das als Fehlschlag erkennen."""
    monkeypatch.setattr(mustang, "_run", lambda args: ("", "", 0))
    out = tmp_path / "out.pdf"  # wird nie erzeugt
    assert mustang.combine(tmp_path / "in.pdf", tmp_path / "in.xml", out) is False


def test_combine_true_when_output_written(monkeypatch, tmp_path):
    out = tmp_path / "out.pdf"

    def fake_run(args):
        out.write_bytes(b"%PDF-1.4")
        return ("", "", 0)

    monkeypatch.setattr(mustang, "_run", fake_run)
    assert mustang.combine(tmp_path / "in.pdf", tmp_path / "in.xml", out) is True


def test_combine_false_when_output_written_but_rc_nonzero(monkeypatch, tmp_path):
    out = tmp_path / "out.pdf"

    def fake_run(args):
        out.write_bytes(b"%PDF-1.4")
        return ("", "boom", 1)

    monkeypatch.setattr(mustang, "_run", fake_run)
    assert mustang.combine(tmp_path / "in.pdf", tmp_path / "in.xml", out) is False


def test_combine_passes_noninteractive_flags(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args):
        captured["args"] = args
        (tmp_path / "out.pdf").write_bytes(b"%PDF")
        return ("", "", 0)

    monkeypatch.setattr(mustang, "_run", fake_run)
    mustang.combine(tmp_path / "in.pdf", tmp_path / "in.xml", tmp_path / "out.pdf")
    args = captured["args"]
    assert "--no-additional-attachments" in args
    assert "--format" in args and "zf" in args


def test_combine_removes_stale_output_first(monkeypatch, tmp_path):
    """Eine alte Datei am Zielpfad darf einen Fehlschlag nicht maskieren."""
    out = tmp_path / "out.pdf"
    out.write_bytes(b"stale")
    monkeypatch.setattr(mustang, "_run", lambda args: ("", "", 0))  # schreibt nichts
    assert mustang.combine(tmp_path / "in.pdf", tmp_path / "in.xml", out) is False
    assert not out.exists()


def test_combine_false_when_output_empty(monkeypatch, tmp_path):
    """rc=0 aber 0-Byte-Datei ist kein Erfolg (korruptes/leeres Ergebnis)."""
    out = tmp_path / "out.pdf"

    def fake_run(args):
        out.write_bytes(b"")
        return ("", "", 0)

    monkeypatch.setattr(mustang, "_run", fake_run)
    assert mustang.combine(tmp_path / "in.pdf", tmp_path / "in.xml", out) is False


# --- extract_xml() Round-Trip: aus einem echten ZUGFeRD-PDF die XML zurückholen ---
# (#98 P2) extract_xml existierte ungetestet. Der Round-Trip beweist, dass die
# eingebettete Factur-X-XML wieder extrahierbar ist — Grundlage für den künftigen
# E-Rechnungs-Empfang (Scope-Spec 2026-07-17).
import pytest
from datetime import date
from decimal import Decimal

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdfa, pdf_generator, zugferd_xml
import defusedxml.ElementTree as DET


def _content_tree(root):
    """Normalisierte, vergleichbare Darstellung eines XML-Baums: (Tag inkl.
    Namespace-URI, sortierte Attribute, getrimmter Textinhalt, Kinder in
    Reihenfolge). Ignoriert Einrückungs-Whitespace (tail/pretty-print) und
    Präfix-Unterschiede (ElementTree löst Präfixe zu {uri}local auf), erkennt
    aber jede echte Inhaltsabweichung (fehlende/andere Werte, Reihenfolge)."""
    return (
        root.tag,
        dict(sorted(root.attrib.items())),
        (root.text or "").strip(),
        [_content_tree(child) for child in root],
    )


@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
def test_extract_xml_roundtrip(tmp_path):
    company = Company(id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
                      zip_code="12345", city="Musterstadt", country="DE",
                      tax_number="123/456/78901", vat_id="DE123456789",
                      bank_iban="DE00123456780000000000")
    customer = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                        zip_code="10115", city="Berlin", country="DE")
    inv = Invoice(invoice_number="RE-2026-XTR", issue_date=date(2026, 7, 8),
                  delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22), currency="EUR",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"), tax_category="S",
                  payment_terms="Zahlbar in 14 Tagen.")
    inv.customer = customer
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("2"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                             tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))]

    xml = zugferd_xml.generate_xml(inv, company)
    visual = tmp_path / "visual.pdf"
    pdf_generator.generate_pdf(inv, company, visual)
    pdfa_pdf = tmp_path / "pdfa.pdf"
    assert pdfa.to_pdfa3(visual, pdfa_pdf, title=inv.invoice_number)
    xml_in = tmp_path / "in.xml"
    xml_in.write_text(xml, encoding="utf-8")
    zugferd_pdf = tmp_path / "zugferd.pdf"
    assert mustang.combine(pdfa_pdf, xml_in, zugferd_pdf)

    out_xml = tmp_path / "extracted.xml"
    assert mustang.extract_xml(zugferd_pdf, out_xml) is True
    assert out_xml.exists()

    # E2 (#98): nicht nur Root-Substring — der INHALT der extrahierten XML muss
    # dem eingebetteten `zugferd_xml` entsprechen. Byte-Vergleich wäre zu spröde
    # (Mustang darf reserialisieren: XML-Deklaration, Whitespace, Präfixe), daher
    # Vergleich der normalisierten Element-Bäume. Ein Payload-Swap / Truncation /
    # Wert-Mangle im combine/extract-Pfad bricht das → rot.
    src_root = DET.fromstring(xml.encode("utf-8"))
    out_root = DET.fromstring(out_xml.read_bytes())
    assert _content_tree(out_root) == _content_tree(src_root)


# ── Zeitgrenze: ein langsamer Rechner darf kein Absturz sein ────────────────────

import subprocess
from unittest.mock import patch


def _zeitgrenze(*a, **k):
    raise subprocess.TimeoutExpired(cmd="java", timeout=60)


def test_validate_meldet_die_zeitgrenze_als_ungueltig_statt_zu_werfen():
    """`subprocess.run(..., timeout=60)` wirft `TimeoutExpired`, wenn die JVM laenger
    braucht — auf einem betagten Rechner oder unter Last keine Ausnahme, sondern
    Alltag (in der eigenen Suite am 10.08.2026 unter paralleler Bauarbeit passiert).

    Fliegt die Ausnahme durch, umgeht sie im Finalisieren die gesamte
    Aufraeumlogik: kein `unlink`, kein `rollback`, ein 500er statt eines Satzes,
    und im GoBD-Verzeichnis bleibt eine verwaiste PDF mit echter Rechnungsnummer
    liegen. Eine ueberschrittene Zeitgrenze muss sich deshalb wie eine
    fehlgeschlagene Pruefung verhalten: ungueltig, aber geordnet.
    """
    with patch("app.services.mustang.subprocess.run", side_effect=_zeitgrenze):
        ergebnis = mustang.validate(Path("/tmp/egal.xml"))

    assert ergebnis["is_valid"] is False
    assert "Zeit" in ergebnis["raw"], f"Der Grund fehlt in der Meldung: {ergebnis['raw']}"


def test_combine_meldet_die_zeitgrenze_als_fehlschlag_statt_zu_werfen(tmp_path):
    """Gleiches fuer das Einbetten. `combine` liefert ohnehin nur True/False —
    eine Zeitgrenze ist ein False, kein Abbruch des ganzen Aufrufs."""
    with patch("app.services.mustang.subprocess.run", side_effect=_zeitgrenze):
        assert mustang.combine(tmp_path / "a.pdf", tmp_path / "a.xml",
                               tmp_path / "out.pdf") is False


def test_extract_xml_meldet_die_zeitgrenze_als_fehlschlag_statt_zu_werfen(tmp_path):
    with patch("app.services.mustang.subprocess.run", side_effect=_zeitgrenze):
        assert mustang.extract_xml(tmp_path / "a.pdf", tmp_path / "out.xml") is False
