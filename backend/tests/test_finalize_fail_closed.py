"""
Fail-closed Finalize (#98 P0.1, Entscheidung 2026-07-22): eine E-Rechnung OHNE
eingebettete ZUGFeRD-XML ist seit 2025 rechtlich unvollständig. Schlägt die
Einbettung fehl (Ghostscript/Mustang nicht verfügbar, `combine` liefert False),
darf die Rechnung NICHT `issued` werden — sie bleibt `draft`, es geht nichts
verloren (kein Commit, Zwischen-PDFs werden entfernt). Das ersetzt den alten
„Fallback = issued + *_visual.pdf" (test_finalize_fallback.py), der genau dieses
Compliance-Loch zementierte.

ECHTES Postgres mit einer GÜLTIGEN Rechnung (Gate + Commit haben Zähne); nur die
Pipeline-Stufen werden gepatcht, um den Fail-closed-Pfad deterministisch und ohne
Ghostscript/Mustang auszulösen.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.config import get_settings
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from tests.helpers.finalize_pipeline import (
    cleanup,
    client,
    fake_generate_pdf,
    finalize_with_fake_pipeline,
    patched_success_pipeline,
    valid_draft,
    valid_mustang,
)

settings = get_settings()


def teardown_function():
    app.dependency_overrides.clear()


def test_finalize_blocks_and_stays_draft_when_combine_fails(pg_session):
    inv = valid_draft(pg_session)
    number = inv.invoice_number
    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", return_value=True), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.routers.invoices.mustang.combine", return_value=False):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
        assert r.status_code == 400, r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "draft"          # NICHT issued
        assert row.pdf_filename is None        # kein Visual-Fallback zementiert
        assert row.zugferd_xml is None         # nicht committet (rollback)
        # Kein verwaistes Zwischen-PDF auf der Platte
        assert not (settings.storage_path / "pdfs" / f"{number}_visual.pdf").exists()
        assert not (settings.storage_path / "pdfs" / f"{number}.pdf").exists()
    finally:
        cleanup(number)


def test_finalize_blocks_when_jar_unavailable(pg_session):
    inv = valid_draft(pg_session)
    number = inv.invoice_number
    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.mustang.jar_available", return_value=False):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
        assert r.status_code == 400, r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "draft"
        assert row.pdf_filename is None
        assert not (settings.storage_path / "pdfs" / f"{number}_visual.pdf").exists()
    finally:
        cleanup(number)


def test_finalize_succeeds_creates_zugferd_pdf_and_cleans_visual(pg_session):
    inv = valid_draft(pg_session)
    number = inv.invoice_number

    def _fake_combine(pdf_path, xml_path, out_path, *a, **k):
        out_path.write_bytes(b"%PDF-zugferd")
        return True

    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", return_value=True), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.routers.invoices.mustang.combine", side_effect=_fake_combine), \
             patch("app.routers.invoices.mustang.validate", return_value=valid_mustang()):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
        assert r.status_code == 303
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "issued"
        assert row.pdf_filename == f"{number}.pdf"          # ZUGFeRD-PDF
        assert (settings.storage_path / "pdfs" / f"{number}.pdf").exists()
        assert not (settings.storage_path / "pdfs" / f"{number}_visual.pdf").exists()
    finally:
        cleanup(number)


def test_finalize_blocks_when_combined_pdf_fails_mustang_validate(pg_session):
    """E1 (#98 Hardness): `combine` kann eine Datei schreiben und True liefern,
    obwohl das kombinierte PDF von einem Empfänger-/Prüfer-System abgelehnt würde
    (Fake-combine schrieb bisher `b"%PDF-zugferd"` → Suite grün, Empfänger bounced).
    Finalize MUSS das kombinierte PDF via Mustang validieren (is_valid + XML:valid)
    und bei rotem Ergebnis fail-closed bleiben: draft, 400, kein Artefakt zementiert,
    kein Commit."""
    inv = valid_draft(pg_session)
    number = inv.invoice_number

    def _fake_combine(pdf_path, xml_path, out_path, *a, **k):
        out_path.write_bytes(b"%PDF-not-really-zugferd")
        return True

    invalid = {"is_valid": False,
               "raw": "Parsed PDF:invalid\n[error] no embedded XML found",
               "errors": ["[error] no embedded XML found"], "warnings": []}
    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", return_value=True), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.routers.invoices.mustang.combine", side_effect=_fake_combine), \
             patch("app.routers.invoices.mustang.validate", return_value=invalid):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
        assert r.status_code == 400, r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "draft"               # NICHT issued
        assert row.pdf_filename is None
        assert row.zugferd_xml is None             # rollback
        assert not (settings.storage_path / "pdfs" / f"{number}.pdf").exists()
        assert not (settings.storage_path / "pdfs" / f"{number}_visual.pdf").exists()
    finally:
        cleanup(number)


def test_finalize_blocks_when_combined_pdf_valid_pdfa_but_no_xml(pg_session):
    """E1-Randfall: ein bares PDF/A (is_valid=False, aber KEINE [error]-Marker,
    „XML:valid" fehlt) darf NICHT als E-Rechnung durchgehen. Der Gate verlangt
    explizit `XML:valid`, nicht nur „keine Fehler"."""
    inv = valid_draft(pg_session)
    number = inv.invoice_number

    def _fake_combine(pdf_path, xml_path, out_path, *a, **k):
        out_path.write_bytes(b"%PDF-bare-pdfa")
        return True

    # Bare PDF/A: Mustang meldet isCompliant=true, aber NICHT "Parsed PDF:valid"
    # und NICHT "XML:valid" — is_valid ist False (keine XML). Kein [error]-Marker.
    bare_pdfa = {"is_valid": False,
                 "raw": "<pdf>isCompliant=true flavour=3b</pdf>\nSummary: 0 errors",
                 "errors": [], "warnings": []}
    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", return_value=True), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.routers.invoices.mustang.combine", side_effect=_fake_combine), \
             patch("app.routers.invoices.mustang.validate", return_value=bare_pdfa):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
        assert r.status_code == 400, r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "draft"
        assert row.pdf_filename is None
    finally:
        cleanup(number)


def test_finalize_requires_xml_valid_not_just_is_valid(pg_session):
    """E1: die `XML:valid`-Klausel hat eigene Zähne. Ein Mustang-Ergebnis mit
    is_valid=True, aber OHNE `XML:valid` im raw (z. B. nur PDF/A-konform, XML-Schicht
    nicht bestätigt) darf NICHT als E-Rechnung durchgehen — ein reiner is_valid-Check
    würde das durchlassen."""
    inv = valid_draft(pg_session)
    number = inv.invoice_number

    def _fake_combine(pdf_path, xml_path, out_path, *a, **k):
        out_path.write_bytes(b"%PDF-pdfa-only")
        return True

    no_xml = {"is_valid": True,
              "raw": "Parsed PDF:valid\nSummary: 0 errors",   # kein "XML:valid"
              "errors": [], "warnings": []}
    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", return_value=True), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.routers.invoices.mustang.combine", side_effect=_fake_combine), \
             patch("app.routers.invoices.mustang.validate", return_value=no_xml):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
        assert r.status_code == 400, r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "draft"
        assert row.pdf_filename is None
    finally:
        cleanup(number)


def test_fehlermeldung_nennt_den_grund_aus_der_pruefung(pg_session):
    """Die Meldung sagte nur „PDF/A- oder Mustang-Schritt fehlgeschlagen".

    In der Abnahme am 2026-08-09 stand dahinter eine Regel, die man ohne den
    Prüfbericht nicht erraten kann (`BR-CO-26`, fehlende Verkäufer-Kennung). Ohne
    den Grund bleibt nur „nochmal versuchen", und der Versuch scheitert wieder.
    Deshalb wandert der erste Prüffehler in die Antwort."""
    inv = valid_draft(pg_session)
    number = inv.invoice_number

    def _fake_combine(pdf_path, xml_path, out_path, *a, **k):
        out_path.write_bytes(b"%PDF-not-really-zugferd")
        return True

    grund = ("[BR-CO-26]-In order for the buyer to automatically identify a supplier, "
             "the Seller identifier (BT-29) ... shall be present.")
    invalid = {"is_valid": False, "raw": "Parsed PDF:valid XML:invalid\n" + grund,
               "errors": [grund], "warnings": []}
    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", return_value=True), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.routers.invoices.mustang.combine", side_effect=_fake_combine), \
             patch("app.routers.invoices.mustang.validate", return_value=invalid):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
        assert r.status_code == 400, r.text
        assert "BR-CO-26" in r.text, r.text
    finally:
        cleanup(number)


def test_finalize_bleibt_entwurf_wenn_mustang_in_die_zeitgrenze_laeuft(pg_session):
    """Eine ueberschrittene Zeitgrenze muss denselben geordneten Weg nehmen wie
    jede andere fehlgeschlagene Pruefung.

    Gepatcht wird hier bewusst `subprocess.run` und nicht `mustang.combine`: nur so
    laeuft die Ausnahme durch den echten Uebersetzungsschritt in `services/mustang.py`.
    Ein Patch auf `combine` wuerde genau die Stelle ueberspringen, um die es geht.

    Ohne diese Uebersetzung fliegt `TimeoutExpired` an der Aufraeumlogik vorbei: 500
    statt 400, kein `db.rollback()`, und in `storage/pdfs/` bleibt eine verwaiste PDF
    mit echter Rechnungsnummer liegen — im GoBD-Archiv spaeter nicht mehr von einem
    Beleg zu unterscheiden.
    """
    import subprocess
    inv = valid_draft(pg_session)
    number = inv.invoice_number

    def _zeitgrenze(*a, **k):
        raise subprocess.TimeoutExpired(cmd="java", timeout=60)

    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", return_value=True), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.services.mustang.subprocess.run", side_effect=_zeitgrenze):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")

        assert r.status_code == 400, f"Zeitgrenze ergab {r.status_code} statt 400."
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "draft"
        assert row.pdf_filename is None
        assert row.zugferd_xml is None
        assert not (settings.storage_path / "pdfs" / f"{number}.pdf").exists(), \
            "Verwaiste PDF mit echter Rechnungsnummer im GoBD-Verzeichnis."
        assert not (settings.storage_path / "pdfs" / f"{number}_visual.pdf").exists()
        assert not (settings.storage_path / "xml" / f"{number}.xml").exists()
    finally:
        cleanup(number)
