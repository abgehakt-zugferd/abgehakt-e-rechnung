"""Bausteine fuer den sichtbaren PDF-Aufbau in Reihenfolge."""

from __future__ import annotations

from dataclasses import dataclass
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from app.services.adresse import bereinige_adresszeile2
from app.services.belegart import belegart
from app.services.pdf_spalten import spaltenbreiten

from .layout import (
    BORDER,
    GOLD,
    GOLD_TINT,
    INK,
    TABELLE_GROESSE,
    TABELLE_POLSTER,
    TEXT_GRAY,
    TitleBand,
    description_markup,
    logo_flowable,
)
from .logic import (
    build_item_rows,
    document_title,
)
from .payment import payment_text, zahlungsblock


@dataclass(frozen=True)
class Styles:
    normal: ParagraphStyle
    small: ParagraphStyle
    small_right: ParagraphStyle
    small_bold: ParagraphStyle
    right: ParagraphStyle
    absender: ParagraphStyle
    right_bold: ParagraphStyle


def create_styles(body, bold, ta_right) -> Styles:
    normal = ParagraphStyle("Normal", fontName=body, fontSize=9, leading=13, textColor=INK)
    small = ParagraphStyle("small", fontName=body, fontSize=8, textColor=TEXT_GRAY, leading=11)
    small_right = ParagraphStyle("small_right", fontName=body, fontSize=8, textColor=TEXT_GRAY, leading=11, alignment=ta_right)
    small_bold = ParagraphStyle("small_bold", fontName=bold, fontSize=8, textColor=INK)
    right = ParagraphStyle("right", fontName=body, fontSize=9, alignment=ta_right)
    absender = ParagraphStyle("absender", fontName=body, fontSize=6.5, leading=9, textColor=TEXT_GRAY, spaceAfter=3)
    right_bold = ParagraphStyle("right_bold", fontName=bold, fontSize=10, alignment=ta_right, textColor=INK)
    return Styles(normal, small, small_right, small_bold, right, absender, right_bold)


def append_briefkopf_und_logo(story, rollen, width, pixel_font, body_font, styles: Styles):
    seller = rollen.verkaeufer
    contact_text = "<br/>".join(escape(z) for z in _addr_lines(seller))
    brand_box, brand_width = _brand_box(seller.name, width, pixel_font, body_font)
    header_table = Table(
        [[brand_box, Paragraph(contact_text, styles.small_right)]],
        colWidths=[brand_width, width - brand_width],
    )
    header_table.hAlign = "LEFT"
    header_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), body_font),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width=width, thickness=1.5, color=INK, spaceBefore=2, spaceAfter=1))
    story.append(HRFlowable(width=width, thickness=0.5, color=GOLD, spaceAfter=12))


def append_adress_und_angabenblock(story, invoice, rollen, d, width, body_font, styles: Styles):
    seller = rollen.verkaeufer
    customer = rollen.erwerber
    addr_meta = Table(
        [[[Paragraph(escape(_absenderzeile(seller)), styles.absender),
           Paragraph("<br/>".join(escape(z) for z in _customer_addr(customer)), styles.normal)],
          Paragraph(_meta_text(invoice, customer, d), styles.small_right)]],
        colWidths=[width * 0.5, width * 0.5],
    )
    addr_meta.hAlign = "LEFT"
    addr_meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), body_font),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(addr_meta)
    story.append(Spacer(1, 0.8 * cm))


def append_titelband(story, invoice, width, pixel_font, retro_font):
    story.append(TitleBand(width, document_title(invoice), invoice.invoice_number, title_font=pixel_font, number_font=retro_font))
    story.append(Spacer(1, 0.5 * cm))


def append_positionstabelle(story, invoice, d, width, body_font, bold_font):
    item_rows = build_item_rows(invoice, d)
    col_widths = spaltenbreiten(
        item_rows[0], item_rows[1:], width, schrift=body_font, fett=bold_font,
        groesse=TABELLE_GROESSE, polster=2 * TABELLE_POLSTER,
    )
    letzte = len(col_widths) - 1
    items_table = Table(item_rows, colWidths=col_widths, repeatRows=1)
    items_table.hAlign = "LEFT"
    items_table.setStyle(TableStyle(_positionen_style(body_font, bold_font, letzte)))
    story.append(items_table)
    story.append(Spacer(1, 0.5 * cm))


def append_hinweise(story, invoice, d, italic_font):
    tax_cat = getattr(invoice, "tax_category", "S")
    hinweis = d.steuerhinweis(tax_cat)
    if hinweis:
        story.append(Paragraph(hinweis, _notice_style(italic_font)))
        story.append(Spacer(1, 0.3 * cm))


def append_fusstext(story, invoice, styles: Styles):
    # Fusstext (Festlegung 15): unter dem Summenblock, vor dem Zahlungsblock.
    # Der Reverse-Charge-Vermerk steht im Steuerhinweis weiter oben; der
    # Fusstext wiederholt ihn bewusst nicht. Leer druckt nichts.
    fusstext = (getattr(invoice, "fusstext", None) or "").strip()
    if fusstext:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(description_markup(fusstext), styles.small))


def append_zahlungsblock(story, invoice, company, d, styles: Styles, body_font):
    story.append(Spacer(1, 0.8 * cm))
    text = payment_text(invoice, company, d)
    story.extend(zahlungsblock(invoice, company, styles.small, d, text, body_font))


def append_notizen(story, invoice, d, styles: Styles):
    # Ersatzrechnung: Hinweis aus dem Bezug, nicht aus den Bemerkungen, damit
    # er mit ihnen nicht geloescht werden kann (docs/specs/ersatzrechnung.md).
    ersetzt = getattr(invoice, "ersetzte_rechnung", None)
    if ersetzt is not None:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(description_markup(d.ersatz_hinweis.format(
            nummer=ersetzt.invoice_number,
            datum=d.format_datum(ersetzt.issue_date),
        )), styles.small))
    if invoice.notes:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(description_markup(invoice.notes), styles.small))


def _addr_lines(seller):
    lines = [seller.name]
    if seller.address_line1:
        lines.append(seller.address_line1)
    line2 = bereinige_adresszeile2(seller.name, seller.address_line2)
    if line2:
        lines.append(line2)
    lines.append(f"{seller.zip_code} {seller.city}")
    if seller.email:
        lines.append(seller.email)
    if seller.phone:
        lines.append(seller.phone)
    return lines


def _brand_box(name, width, pixel_font, body_font):
    pad = 10
    brand_fontsize = 8
    brand_style = ParagraphStyle("brand", fontName=pixel_font, fontSize=brand_fontsize, leading=13, textColor=INK)
    brand_text = name.upper()
    brand_name = Paragraph(escape(brand_text), brand_style)
    logo_img = logo_flowable()
    name_w = pdfmetrics.stringWidth(brand_text, pixel_font, brand_fontsize)
    logo_w = logo_img.drawWidth if logo_img is not None else 0
    brand_width = min(max(name_w, logo_w) + 2 * pad + 2, width * 0.62)
    brand_rows = [[brand_name]]
    if logo_img is not None:
        brand_rows = [[logo_img], [brand_name]]
    brand_box = Table(brand_rows, colWidths=[brand_width])
    brand_box.setStyle(TableStyle(_brand_style(body_font, logo_img is not None)))
    return brand_box, brand_width


def _brand_style(body_font, mit_logo):
    style_cmds = [
        ("FONTNAME", (0, 0), (-1, -1), body_font),
        ("BOX", (0, 0), (-1, -1), 0.8, INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]
    if mit_logo:
        style_cmds.append(("BOTTOMPADDING", (0, 0), (0, 0), 4))
        style_cmds.append(("TOPPADDING", (0, 1), (0, 1), 2))
    return style_cmds


def _customer_addr(customer):
    cust_addr = [customer.name]
    if customer.address_line1:
        cust_addr.append(customer.address_line1)
    cust_line2 = bereinige_adresszeile2(customer.name, customer.address_line2)
    if cust_line2:
        cust_addr.append(cust_line2)
    cust_addr.append(f"{customer.zip_code} {customer.city}")
    if customer.country and customer.country != "DE":
        cust_addr.append(customer.country)
    return cust_addr


def _meta_text(invoice, customer, d):
    meta_rows = [
        (d.belegnummer_etikett(getattr(invoice, "invoice_type", None)), invoice.invoice_number),
        (d.label_rechnungsdatum, d.format_datum(invoice.issue_date)),
    ]
    if invoice.delivery_date:
        meta_rows.append((d.label_leistungsdatum, d.format_datum(invoice.delivery_date)))
    if invoice.service_period_start and invoice.service_period_end:
        period_str = f"{d.format_datum(invoice.service_period_start)} – {d.format_datum(invoice.service_period_end)}"
        if belegart(getattr(invoice, "invoice_type", None)).intern == "prepayment":
            meta_rows.append((d.label_vorauss_leistungszeitraum, period_str))
        else:
            meta_rows.append((d.label_leistungszeitraum, period_str))
    # Ohne due_date (BR-CO-25) entfällt die Kopfzeile statt leer zu bleiben:
    # der Zahlungsblock unten druckt die payment_terms schon, eine zweite
    # Zeile mit dem Hinweis oben wäre eine Doppelung.
    if invoice.due_date is not None:
        meta_rows.append((d.label_faelligkeit, d.format_datum(invoice.due_date)))
    if getattr(customer, "customer_number", None):
        meta_rows.append((d.label_kundennummer, customer.customer_number))
    if getattr(invoice, "buyer_reference", None):
        meta_rows.append((d.label_ihre_referenz, invoice.buyer_reference))
    if getattr(invoice, "buyer_order_reference", None):
        meta_rows.append((d.label_bestellnummer, invoice.buyer_order_reference))
    if customer.vat_id:
        meta_rows.append((d.label_ust_id_kunde, customer.vat_id))
    return "".join(f"<b>{escape(k)}</b> {escape(str(v))}<br/>" for k, v in meta_rows)


def _absenderzeile(company) -> str:
    """Kleine Rücksendeangabe über der Empfängeranschrift: Firma · Straße · PLZ Ort."""
    teile = [company.name, company.address_line1, f"{company.zip_code} {company.city}"]
    return " · ".join(t.strip() for t in teile if t and t.strip())


def _positionen_style(body_font, bold_font, letzte):
    return [
        ("FONTNAME", (0, 1), (-1, -1), body_font),
        ("FONTNAME", (0, 0), (-1, 0), bold_font),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), TABELLE_GROESSE),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (4, 0), (letzte, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GOLD_TINT]),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), TABELLE_POLSTER),
        ("RIGHTPADDING", (0, 0), (-1, -1), TABELLE_POLSTER),
    ]


def _notice_style(italic_font):
    return ParagraphStyle(
        "notice",
        fontName=italic_font,
        fontSize=8,
        textColor=TEXT_GRAY,
        borderColor=BORDER,
        borderWidth=0.5,
        borderPadding=6,
        leading=12,
    )


