"""Einstiegspunkt fuer die Rechnungs-PDF-Erzeugung."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models.company import Company
from app.models.invoice import Invoice
from app.services.auftragszahlung import ohne_ueberweisungsaufforderung
from app.services.belegrollen import besetzung
from app.services.pdf_fonts import register_fonts
from app.services.pdf_fuss import Fuss, leinwand

from .blocks import (
    append_adress_und_angabenblock,
    append_briefkopf_und_logo,
    append_fusstext,
    append_hinweise,
    append_notizen,
    append_positionstabelle,
    append_titelband,
    append_zahlungsblock,
    create_styles,
)
from .layout import description_markup, draft_watermark
from .logic import belegdarstellung, ist_gutschrift
from .totals import append_steuer_und_summenblock


def generate_pdf(invoice: Invoice, company: Company, output_path: Path, draft: bool = False) -> None:
    # P8: Null-Checks für kritische Objekte
    if not invoice:
        raise ValueError("Rechnung darf nicht None sein")
    if not company:
        raise ValueError("Firmendaten dürfen nicht None sein")
    if not invoice.customer:
        raise ValueError("Rechnung hat keinen Kunden zugeordnet (customer_id fehlt)")

    d = belegdarstellung(invoice)
    fonts = register_fonts()
    body = fonts["body"]
    styles = create_styles(body, fonts["body_bold"], TA_RIGHT)
    rollen = besetzung(invoice, company, invoice.customer)
    width = A4[0] - 4 * cm
    doc, canvasmaker = _doc_und_canvas(output_path, invoice, company, d, rollen, body)
    story = _story(invoice, company, d, rollen, width, fonts, styles)
    if draft:
        watermark = draft_watermark(body, d.stempel_entwurf)
        doc.build(story, canvasmaker=canvasmaker, onFirstPage=watermark, onLaterPages=watermark)
        return
    doc.build(story, canvasmaker=canvasmaker)


def _doc_und_canvas(output_path, invoice, company, d, rollen, body):
    mit_bank = not ist_gutschrift(invoice) and not ohne_ueberweisungsaufforderung(invoice)
    fuss = Fuss(company, d, rollen=rollen, schrift=body, breite=A4[0] - 4 * cm,
                links=2 * cm, mit_bank=mit_bank)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=fuss.unterer_rand,
    )
    canvasmaker = leinwand(body, d.seite_muster, fuss, rechts=A4[0] - 2 * cm)
    return doc, canvasmaker


def _story(invoice, company, d, rollen, width, fonts, styles):
    story = []
    append_briefkopf_und_logo(story, rollen, width, fonts["pixel"], fonts["body"], styles)
    append_adress_und_angabenblock(story, invoice, rollen, d, width, fonts["body"], styles)
    append_titelband(story, invoice, width, fonts["pixel"], fonts["retro"])
    _append_kopftext(story, invoice, styles)
    append_positionstabelle(story, invoice, d, width, fonts["body"], fonts["body_bold"])
    append_hinweise(story, invoice, d, fonts["body_italic"])
    append_steuer_und_summenblock(story, invoice, d, styles, fonts["body"], fonts["body_bold"])
    append_fusstext(story, invoice, styles)
    append_zahlungsblock(story, invoice, company, d, styles, fonts["body"])
    append_notizen(story, invoice, d, styles)
    return story


def _append_kopftext(story, invoice, styles):
    # Kopftext (Festlegung 15): Rechnungsinhalt aus dem Kundenstamm, ueber der
    # Positionstabelle. Dieselbe Aufbereitung wie Beschreibungen — auch hier ist
    # der rohe Text kein Markup. Leer druckt nichts.
    kopftext = (getattr(invoice, "kopftext", None) or "").strip()
    if kopftext:
        story.append(Paragraph(description_markup(kopftext), styles.small))
        story.append(Spacer(1, 0.3 * cm))
