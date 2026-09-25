"""
Erstellt das visuelle Rechnungs-PDF im deutschen Standard mit ReportLab.
Das PDF wird anschließend von Mustang mit dem ZUGFeRD-XML kombiniert.
"""
import io
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
    Image, Flowable,
)
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.enums import TA_RIGHT, TA_LEFT, TA_CENTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from app.config import get_settings
from app.models.invoice import Invoice
from app.models.company import Company
from app.services.adresse import bereinige_adresszeile2
from app.services.pdf_fonts import register_fonts
from app.services.bankverbindung import iban_fuer_ausgabe
from app.services.epc_qr import build_epc_payload, qr_png_bytes
from app.services.iban import IbanProfil
from app.services.zugferd_xml import EXEMPTION_REASONS
from app.services.belegart import belegart
from app.services.belegsprache import Belegdarstellung, darstellung, resolve_belegsprache

# ── Firmenlogo ───────────────────────────────────────────────────────────────
# Das Logo gehört der Nutzerin, nicht dem Auslieferungs-Image (#99 §4.3, L4):
# es liegt als `logo.png` im storage-Volume, das pro Installation verschieden ist.
# Ein Logo unter `app/assets/` wäre in JEDEM ausgelieferten Image — die
# Pilotnutzerin bekäme ein fremdes Firmenzeichen auf ihre Rechnung.
LOGO_DATEINAME = "logo.png"
LOGO_TARGET_HEIGHT = 30    # pt — Zielhöhe im Header
LOGO_MAX_WIDTH = 120       # pt — Deckel, damit eine Wortmarke den Header nicht sprengt


def _logo_path() -> Path | None:
    """Pfad zum Firmenlogo im storage-Volume, oder None wenn keines hinterlegt ist."""
    pfad = get_settings().storage_path / LOGO_DATEINAME
    return pfad if pfad.exists() else None


def _logo_flowable():
    """Passend skaliertes Image-Flowable des Firmenlogos, oder None ohne Logo.

    Skaliert auf Zielhöhe, deckelt aber die Breite: hoch/schmale Logos treffen die
    Zielhöhe, breite Wortmarken laufen sonst quer durch den Header.
    """
    path = _logo_path()
    if path is None:
        return None
    iw, ih = ImageReader(str(path)).getSize()
    h = LOGO_TARGET_HEIGHT
    w = h * iw / ih
    if w > LOGO_MAX_WIDTH:
        w = LOGO_MAX_WIDTH
        h = w * ih / iw
    return Image(str(path), width=w, height=h)

# PDF-Steuerhinweise kommen aus Belegdarstellung (sprachabhaengig fuer E/K/O;
# AE immer zweisprachig). Ob eine Steuerzeile angezeigt wird, richtet sich weiter
# nach den Kategorien in EXEMPTION_REASONS (XML-Tabelle), nicht nach dem Wortlaut.
TAX_NOTICE_KATEGORIEN = frozenset(EXEMPTION_REASONS)

GUTSCHRIFT_TYPEN = frozenset({"credit_note", "credit", "storno", "self_billing"})


def _ist_gutschrift(invoice) -> bool:
    return getattr(invoice, "invoice_type", None) in GUTSCHRIFT_TYPEN


def _belegdarstellung(invoice) -> Belegdarstellung:
    """Sprache der Rechnung → Darstellung. Unbekannt = harter Fehler vor Ausgabe."""
    roh = getattr(invoice, "document_language", None)
    if roh is None:
        roh = "de"
    return darstellung(resolve_belegsprache(roh))


def _zahlung_an_kunde(invoice) -> bool:
    """Gutschrift: Überweisung an den Kunden (nicht an die Firma)."""
    return _ist_gutschrift(invoice)


def _zahlungs_empfaenger(invoice, company):
    """(Name, IBAN, BIC, Bankname) für Anzeige und EPC-QR, oder None."""
    customer = invoice.customer
    if _zahlung_an_kunde(invoice):
        if not customer or not customer.bank_iban:
            return None
        return (
            customer.name,
            customer.bank_iban,
            customer.bank_bic,
            customer.bank_name,
        )
    if company.bank_iban:
        return (
            company.name,
            company.bank_iban,
            company.bank_bic,
            company.bank_name,
        )
    return None


def _epc_qr_anhaengen(story, invoice, company, small, d: Belegdarstellung) -> None:
    ziel = _zahlungs_empfaenger(invoice, company)
    if not ziel:
        return
    name, iban, bic, bank_name = ziel
    wer = "Kunde" if _zahlung_an_kunde(invoice) else "Firma"
    # Option A: Registry-ungueltige Bestands-IBAN bricht die Erzeugung ab
    # (nicht still im Klartext weitergeben und nur den QR unterdruecken).
    iban_norm = iban_fuer_ausgabe(iban, wer=wer, profil=IbanProfil.REGISTRY)
    bank_parts = [f"IBAN: {iban_norm}"]
    if bic:
        bank_parts.append(f"BIC: {bic}")
    if bank_name:
        bank_parts.append(bank_name)
    story.append(Paragraph(" · ".join(bank_parts), small))
    story.append(Paragraph(
        f"{d.label_verwendungszweck} {invoice.invoice_number}", small,
    ))
    try:
        payload = build_epc_payload(
            beneficiary_name=name,
            iban=iban_norm,
            bic=bic,
            amount=invoice.gross_total,
            currency=getattr(invoice, "currency", "EUR") or "EUR",
            remittance=invoice.invoice_number,
        )
        story.append(Spacer(1, 0.4 * cm))
        story.append(Image(io.BytesIO(qr_png_bytes(payload)), width=3.5 * cm, height=3.5 * cm))
        story.append(Paragraph(d.label_scan_to_pay, small))
    except ValueError:
        # EPC_SCT strenger als REGISTRY: kein falscher Girocode, Klartext bleibt.
        pass


def _document_title(invoice) -> str:
    """Sichtbarer Belegtitel aus Belegdarstellung zur Belegsprache.
    Unbekannte Typen werfen UnknownInvoiceTypeError (fail-closed, wie XML)."""
    art = belegart(getattr(invoice, "invoice_type", None))
    return _belegdarstellung(invoice).titel(art.intern)


INK = colors.HexColor("#1a1a2e")          # Fließtext/Überschriften
GOLD = colors.HexColor("#9c7a00")         # print-sicheres Dunkelgold (Linien/Akzente)
GOLD_TINT = colors.HexColor("#f4eeda")    # sehr helle Gold-Tönung (Zeilen/Band)
BORDER = colors.HexColor("#d9cfa6")       # warme, helle Rasterlinie
TEXT_GRAY = colors.HexColor("#5b5b66")    # Sekundärtext, druckkontraststark


# Die Geld-/Mengenformatierung liegt in Belegdarstellung (zustandslos je Sprache).
# Vorher: Alias auf darstellung.euro — der blieb deutsch und war der S3-Risikopfad.


def _pct(v: Decimal) -> str:
    pct = v.quantize(Decimal("0"))
    return f"{pct} %"


class TitleBand(Flowable):
    """Belegtitel (Pixelschrift, links) + Rechnungsnummer (Retro, rechts) auf
    EINER gemeinsamen Grundlinie innerhalb eines gerahmten Bandes.

    Warum ein eigenes Flowable statt einer Tabelle: In einer Tabellenzeile
    richtet ReportLab jede Zelle einzeln aus (VALIGN), sodass Titel und Nummer
    bei unterschiedlichen Schriftgrößen auf verschiedenen Grundlinien sitzen.
    Hier zeichnen wir beide Strings mit demselben `baseline`-y → garantiert
    eine Linie.
    """

    def __init__(self, width, title, number, title_font, number_font,
                 title_size=13, number_size=22, pad=10, height=32,
                 bg=None, border=None, title_color=None, number_color=None):
        super().__init__()
        self.hAlign = "LEFT"  # bündig mit den Tabellen darunter (nicht zentriert)
        self.width = width
        self.height = height
        self.title = title
        self.number = number
        self.title_font = title_font
        self.number_font = number_font
        self.title_size = title_size
        self.number_size = number_size
        self.pad = pad
        self.bg = bg if bg is not None else GOLD_TINT
        self.border = border if border is not None else GOLD
        self.title_color = title_color if title_color is not None else INK
        self.number_color = number_color if number_color is not None else GOLD

    def wrap(self, aW, aH):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.setFillColor(self.bg)
        c.setStrokeColor(self.border)
        c.setLineWidth(1)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=1)

        # Gemeinsame Grundlinie: das größere (Nummern-)Glyph optisch mittig im
        # Band, Titel sitzt auf derselben Linie.
        baseline = (self.height - self.number_size) / 2 + self.number_size * 0.20

        c.setFillColor(self.title_color)
        c.setFont(self.title_font, self.title_size)
        c.drawString(self.pad, baseline, self.title)

        c.setFillColor(self.number_color)
        c.setFont(self.number_font, self.number_size)
        c.drawRightString(self.width - self.pad, baseline, self.number)


def _item_style():
    """Absatzstil für umbrechende Positionsbeschreibungen."""
    fonts = register_fonts()
    return ParagraphStyle(
        "item_desc", fontName=fonts["body"], fontSize=8.5, leading=10.5, textColor=INK
    )


def _description_markup(text: str) -> str:
    """Beschreibung für `Paragraph` aufbereiten.

    `Paragraph` interpretiert Mini-HTML — eine rohe Beschreibung ist damit kein Text,
    sondern Markup. Zwei Folgen, beide 2026-08-03 am Container verifiziert:
    ein `<` gefolgt von einem Buchstaben (`Mengenrabatt 5<x`) bricht die
    PDF-Erzeugung mit `ValueError: unclosed tags`, und ein `<b>` würde fett
    rendern statt dazustehen. Also erst escapen …
    """
    escaped = escape(text or "")
    # … und danach die einzigen Umbrüche einsetzen, die `Paragraph` kennt: `\n`
    # ist für ihn kein Zeilenumbruch, sondern gewöhnlicher Whitespace.
    return escaped.replace("\n", "<br/>")


def _zeigt_steuer(invoice: Invoice) -> bool:
    """Ob der Beleg überhaupt Umsatzsteuer ausweist.

    Maßstab sind die Kategorien in EXEMPTION_REASONS: wo ein Befreiungsgrund
    steht, ist eine Steuerzeile ein Widerspruch — die Rechnung sagte oben
    „hier wird keine Umsatzsteuer ausgewiesen" und rechnete unten „zzgl. 0 %
    MwSt. — 0,00 €" vor.

    Es geht dabei nicht um § 14c: ein Betrag von null ist kein unrichtiger
    Steuerausweis. Es geht um Verständlichkeit, und bei AE um mehr als das — der
    Empfänger einer Reverse-Charge-Rechnung muss erkennen, dass ER die Steuer
    schuldet, und keine Zeile lesen, die einen Steuervorgang mit dem Ergebnis null
    nahelegt.
    """
    return getattr(invoice, "tax_category", "S") not in TAX_NOTICE_KATEGORIEN


def _build_item_rows(invoice: Invoice, d: Belegdarstellung) -> list[list]:
    """Zeilen für die Positionstabelle. Die Beschreibung wird als Paragraph
    ausgegeben, damit sie in ihrer Spalte umbricht statt überzulaufen."""
    desc_style = _item_style()
    mit_steuer = _zeigt_steuer(invoice)
    kopf = [
        d.label_pos, d.label_beschreibung, d.label_menge,
        d.label_einheit, d.label_einzelpreis,
    ]
    if mit_steuer:
        kopf.append(d.label_mwst)
    kopf.append(d.label_betrag)
    rows = [kopf]
    waehrung = getattr(invoice, "currency", "EUR") or "EUR"
    for item in invoice.items:
        zeile = [
            str(item.position),
            Paragraph(_description_markup(item.description), desc_style),
            # NICHT `str(x.normalize())`: das kippt bei durch zehn teilbaren
            # Mengen in die Exponentialform — 120 Stunden stünden als "1.2E+2"
            # auf der Rechnung an den Kunden.
            d.format_menge(item.quantity),
            item.unit,
            d.format_betrag(item.unit_price, waehrung),
        ]
        if mit_steuer:
            zeile.append(_pct(item.tax_rate))
        zeile.append(d.format_betrag(item.net_amount, waehrung))
        rows.append(zeile)
    return rows


def _draft_watermark(font_name: str, text: str):
    """`onPage`-Callback, der ein diagonales Stempelwort über die Seite legt.

    Der Text wird mit dem EINGEBETTETEN Body-Font gezeichnet, nicht mit einem
    Standard-14-Font. Für die Vorschau selbst ist das folgenlos (sie läuft nie durch
    die Ghostscript/Mustang-Pipeline), aber derselbe Generator erzeugt auch das echte
    PDF — ein nicht eingebetteter Font wäre eine Falle für den Nächsten, der das
    Wasserzeichen wiederverwendet (docs/DEV-DOCU.md, „PDF/A-Schriften einbetten").
    """
    def zeichne(canvas, doc):
        canvas.saveState()
        canvas.setFont(font_name, 84)
        canvas.setFillColor(colors.Color(0.55, 0.55, 0.62, alpha=0.20))
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(52)
        canvas.drawCentredString(0, 0, text)
        canvas.restoreState()
    return zeichne


def generate_pdf(invoice: Invoice, company: Company, output_path: Path,
                 draft: bool = False) -> None:
    # P8: Null-Checks für kritische Objekte
    if not invoice:
        raise ValueError("Rechnung darf nicht None sein")
    if not company:
        raise ValueError("Firmendaten dürfen nicht None sein")
    if not invoice.customer:
        raise ValueError("Rechnung hat keinen Kunden zugeordnet (customer_id fehlt)")

    d = _belegdarstellung(invoice)
    waehrung = getattr(invoice, "currency", "EUR") or "EUR"

    def money(v):
        return d.format_betrag(v, waehrung)

    fonts = register_fonts()
    BODY = fonts["body"]
    BOLD = fonts["body_bold"]
    ITALIC = fonts["body_italic"]
    PIXEL = fonts["pixel"]
    RETRO = fonts["retro"]

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2.5 * cm,
    )

    normal = ParagraphStyle("Normal", fontName=BODY, fontSize=9, leading=13, textColor=INK)
    small = ParagraphStyle("small", fontName=BODY, fontSize=8, textColor=TEXT_GRAY, leading=11)
    small_right = ParagraphStyle("small_right", fontName=BODY, fontSize=8, textColor=TEXT_GRAY, leading=11, alignment=TA_RIGHT)
    small_bold = ParagraphStyle("small_bold", fontName=BOLD, fontSize=8, textColor=INK)
    right = ParagraphStyle("right", fontName=BODY, fontSize=9, alignment=TA_RIGHT)
    right_bold = ParagraphStyle("right_bold", fontName=BOLD, fontSize=10, alignment=TA_RIGHT, textColor=INK)

    story = []
    W = A4[0] - 4 * cm

    addr_lines = [company.name]
    if company.address_line1:
        addr_lines.append(company.address_line1)
    line2 = bereinige_adresszeile2(company.name, company.address_line2)
    if line2:
        addr_lines.append(line2)
    addr_lines.append(f"{company.zip_code} {company.city}")
    if company.email:
        addr_lines.append(company.email)
    if company.phone:
        addr_lines.append(company.phone)

    contact_text = "<br/>".join(addr_lines)

    PAD = 10
    brand_fontsize = 8
    brand_style = ParagraphStyle(
        "brand", fontName=PIXEL, fontSize=brand_fontsize, leading=13, textColor=INK
    )
    brand_text = company.name.upper()
    brand_name = Paragraph(brand_text, brand_style)

    logo_img = _logo_flowable()
    name_w = pdfmetrics.stringWidth(brand_text, PIXEL, brand_fontsize)
    logo_w = logo_img.drawWidth if logo_img is not None else 0
    BRAND_W = min(max(name_w, logo_w) + 2 * PAD + 2, W * 0.62)
    brand_rows = []
    brand_style_cmds = [
        ("FONTNAME", (0, 0), (-1, -1), BODY),
        ("BOX", (0, 0), (-1, -1), 0.8, INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]
    if logo_img is not None:
        brand_rows.append([logo_img])
        brand_style_cmds.append(("BOTTOMPADDING", (0, 0), (0, 0), 4))
        brand_style_cmds.append(("TOPPADDING", (0, 1), (0, 1), 2))
    brand_rows.append([brand_name])

    brand_box = Table(brand_rows, colWidths=[BRAND_W])
    brand_box.setStyle(TableStyle(brand_style_cmds))

    header_table = Table(
        [[brand_box, Paragraph(contact_text, small_right)]],
        colWidths=[BRAND_W, W - BRAND_W],
    )
    header_table.hAlign = "LEFT"
    header_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), BODY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (1, 0), (1, 0), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(header_table)
    story.append(HRFlowable(width=W, thickness=1.5, color=INK, spaceBefore=2, spaceAfter=1))
    story.append(HRFlowable(width=W, thickness=0.5, color=GOLD, spaceAfter=12))

    customer = invoice.customer
    cust_addr = [customer.name]
    if customer.address_line1:
        cust_addr.append(customer.address_line1)
    cust_line2 = bereinige_adresszeile2(customer.name, customer.address_line2)
    if cust_line2:
        cust_addr.append(cust_line2)
    cust_addr.append(f"{customer.zip_code} {customer.city}")
    if customer.country and customer.country != "DE":
        cust_addr.append(customer.country)

    meta_rows = [
        (d.label_rechnungsnummer, invoice.invoice_number),
        (d.label_rechnungsdatum, d.format_datum(invoice.issue_date)),
    ]
    if invoice.delivery_date:
        meta_rows.append(
            (d.label_leistungsdatum, d.format_datum(invoice.delivery_date))
        )
    if invoice.service_period_start and invoice.service_period_end:
        period_str = (
            f"{d.format_datum(invoice.service_period_start)} – "
            f"{d.format_datum(invoice.service_period_end)}"
        )
        if belegart(getattr(invoice, "invoice_type", None)).intern == "prepayment":
            meta_rows.append((d.label_vorauss_leistungszeitraum, period_str))
        else:
            meta_rows.append((d.label_leistungszeitraum, period_str))
    meta_rows.append((d.label_faelligkeit, d.format_datum(invoice.due_date)))
    if getattr(customer, "customer_number", None):
        meta_rows.append((d.label_kundennummer, customer.customer_number))
    if getattr(invoice, "buyer_reference", None):
        meta_rows.append((d.label_ihre_referenz, invoice.buyer_reference))
    if getattr(invoice, "buyer_order_reference", None):
        meta_rows.append((d.label_bestellnummer, invoice.buyer_order_reference))
    if customer.vat_id:
        meta_rows.append((d.label_ust_id_kunde, customer.vat_id))

    meta_text = "".join(f"<b>{k}</b> {v}<br/>" for k, v in meta_rows)

    addr_meta = Table(
        [[Paragraph("<br/>".join(cust_addr), normal), Paragraph(meta_text, small_right)]],
        colWidths=[W * 0.5, W * 0.5]
    )
    addr_meta.hAlign = "LEFT"
    addr_meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), BODY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
    ]))
    story.append(Spacer(1, 0.5 * cm))
    story.append(addr_meta)
    story.append(Spacer(1, 0.8 * cm))

    story.append(TitleBand(
        W, _document_title(invoice), invoice.invoice_number,
        title_font=PIXEL, number_font=RETRO,
    ))
    story.append(Spacer(1, 0.5 * cm))

    col_widths = [0.9 * cm, None, 1.3 * cm, 1.3 * cm, 2.3 * cm]
    if _zeigt_steuer(invoice):
        col_widths.append(1.4 * cm)
    col_widths.append(2.6 * cm)
    col_widths[1] = W - sum(w for w in col_widths if w is not None)
    letzte = len(col_widths) - 1

    item_rows = _build_item_rows(invoice, d)

    items_table = Table(item_rows, colWidths=col_widths, repeatRows=1)
    items_table.hAlign = "LEFT"
    items_table.setStyle(TableStyle([
        ("FONTNAME", (0, 1), (-1, -1), BODY),
        ("FONTNAME", (0, 0), (-1, 0), BOLD),
        ("BACKGROUND", (0, 0), (-1, 0), INK),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        ("ALIGN", (4, 0), (letzte, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, GOLD_TINT]),
        ("GRID", (0, 0), (-1, -1), 0.3, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 0.5 * cm))

    tax_cat = getattr(invoice, "tax_category", "S")
    hinweis = d.steuerhinweis(tax_cat)
    if hinweis:
        notice_style = ParagraphStyle(
            "notice",
            fontName=ITALIC,
            fontSize=8,
            textColor=TEXT_GRAY,
            borderColor=BORDER,
            borderWidth=0.5,
            borderPadding=6,
            leading=12,
        )
        story.append(Paragraph(hinweis, notice_style))
        story.append(Spacer(1, 0.3 * cm))

    from collections import defaultdict
    tax_groups: dict[Decimal, dict] = defaultdict(lambda: {"basis": Decimal("0"), "tax": Decimal("0")})
    for item in invoice.items:
        tax_groups[item.tax_rate]["basis"] += item.net_amount
        tax_groups[item.tax_rate]["tax"] += item.tax_amount

    totals_data = []
    totals_data.append([Paragraph(d.label_netto, small), Paragraph(money(invoice.net_total), right)])
    if _zeigt_steuer(invoice):
        for rate in sorted(tax_groups.keys()):
            g = tax_groups[rate]
            label = d.steuerzeile(_pct(rate), money(g["basis"]))
            totals_data.append([Paragraph(label, small), Paragraph(money(g["tax"]), right)])
    summen_label = (
        d.label_gutschriftbetrag if _ist_gutschrift(invoice) else d.label_rechnungsbetrag
    )
    totals_data.append([
        Paragraph(f"<b>{summen_label}</b>", small_bold),
        Paragraph(f"<b>{money(invoice.gross_total)}</b>", right_bold)
    ])

    totals_col = W * 0.55
    totals_table = Table(totals_data, colWidths=[totals_col, W - totals_col])
    totals_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), BODY),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LINEABOVE", (0, -1), (-1, -1), 1, GOLD),
        ("TOPPADDING", (0, -1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    totals_wrap = Table([[None, totals_table]], colWidths=[totals_col * 0.1, W - totals_col * 0.1])
    totals_wrap.hAlign = "LEFT"
    totals_wrap.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), BODY),
        ("ALIGN", (1, 0), (1, 0), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(totals_wrap)

    story.append(Spacer(1, 0.8 * cm))
    if _zahlung_an_kunde(invoice) and _zahlungs_empfaenger(invoice, company):
        payment_text = invoice.payment_terms or d.fallback_gutschrift_ueberweisung
    elif _ist_gutschrift(invoice):
        payment_text = invoice.payment_terms or d.fallback_gutschrift_ohne
    else:
        payment_text = invoice.payment_terms or d.fallback_zahlbar
    story.append(Paragraph(payment_text, small))
    _epc_qr_anhaengen(story, invoice, company, small, d)

    if invoice.notes:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(invoice.notes, small))

    story.append(Spacer(1, 0.8 * cm))
    story.append(HRFlowable(width=W, thickness=0.5, color=BORDER, spaceAfter=6))
    footer_parts = []
    if company.vat_id:
        footer_parts.append(f"{d.label_ust_id} {company.vat_id}")
    if company.tax_number:
        footer_parts.append(f"{d.label_steuernummer} {company.tax_number}")
    if footer_parts:
        story.append(Paragraph("  ·  ".join(footer_parts), small))

    def _canvasmaker(*args, **kwargs):
        kwargs["initialFontName"] = BODY
        return Canvas(*args, **kwargs)

    if draft:
        wasserzeichen = _draft_watermark(BODY, d.stempel_entwurf)
        doc.build(story, canvasmaker=_canvasmaker,
                  onFirstPage=wasserzeichen, onLaterPages=wasserzeichen)
    else:
        doc.build(story, canvasmaker=_canvasmaker)
