"""Ersatzrechnung in PDF und GoBD-Export (docs/specs/ersatzrechnung.md, Ergebnis 2 und 3).

Die Zeile im PDF kommt aus dem Bezug selbst, nicht aus den Bemerkungen: wer die
Bemerkungen leert, darf den Hinweis nicht mit loeschen.
"""
from pypdf import PdfReader

from app.models.company import Company
from app.services import pdf_generator
from tests.helpers.ersatzrechnung import ersatz_entwurf, kunde, stornierte


def _pdf_text(inv, company, tmp_path):
    out = tmp_path / "ersatz.pdf"
    pdf_generator.generate_pdf(inv, company, out)
    return "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)


def _ersatz(pg_session, sprache):
    k = kunde(pg_session)
    original = stornierte(pg_session, k)
    ersatz = ersatz_entwurf(pg_session, k, original)
    ersatz.document_language = sprache
    ersatz.notes = None
    pg_session.commit()
    pg_session.refresh(ersatz)
    return original, ersatz


def test_pdf_nennt_die_ersetzte_rechnung(pg_session, tmp_path):
    original, ersatz = _ersatz(pg_session, "de")

    text = _pdf_text(ersatz, pg_session.get(Company, 1), tmp_path)

    assert f"Ersetzt Rechnung {original.invoice_number} vom 08.07.2026." in text


def test_pdf_nennt_die_ersetzte_rechnung_auf_englisch(pg_session, tmp_path):
    original, ersatz = _ersatz(pg_session, "en")

    text = _pdf_text(ersatz, pg_session.get(Company, 1), tmp_path)

    assert f"Replaces invoice {original.invoice_number} dated" in text
