"""
Erstellt das visuelle Rechnungs-PDF im deutschen Standard mit ReportLab.
Das PDF wird anschließend von Mustang mit dem ZUGFeRD-XML kombiniert.
"""
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
from app.darstellung import euro, menge
from app.models.invoice import Invoice
from app.models.company import Company
from app.services.pdf_fonts import register_fonts
from app.services.zugferd_xml import EXEMPTION_REASONS

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

# Derselbe Text wie in der XML, nicht eine Kopie davon: bis #152 standen hier
# eigene Zeichenketten, und als die Kategorie "E" (§ 19 UStG) dazukam, fehlte der
# gesetzlich vorgeschriebene Hinweis auf dem gedruckten Beleg — lautlos, weil das
# PDF ohne Eintrag einfach nichts ausgibt. Ein Alias hat dieses Problem nicht.
TAX_NOTICE = EXEMPTION_REASONS

DOCUMENT_TITLES = {
    "credit_note": "GUTSCHRIFT",
    "credit": "GUTSCHRIFT",
    "storno": "GUTSCHRIFT",
    "correction": "KORREKTURRECHNUNG",
}

GUTSCHRIFT_TYPEN = frozenset({"credit_note", "credit", "storno"})


def _ist_gutschrift(invoice) -> bool:
    return getattr(invoice, "invoice_type", None) in GUTSCHRIFT_TYPEN


def _document_title(invoice) -> str:
    """Sichtbarer Belegtitel passend zum invoice_type (Default: RECHNUNG)."""
    return DOCUMENT_TITLES.get(getattr(invoice, "invoice_type", None), "RECHNUNG")


INK = colors.HexColor("#1a1a2e")          # Fließtext/Überschriften
GOLD = colors.HexColor("#9c7a00")         # print-sicheres Dunkelgold (Linien/Akzente)
GOLD_TINT = colors.HexColor("#f4eeda")    # sehr helle Gold-Tönung (Zeilen/Band)
BORDER = colors.HexColor("#d9cfa6")       # warme, helle Rasterlinie
TEXT_GRAY = colors.HexColor("#5b5b66")    # Sekundärtext, druckkontraststark


# Die Regel steht jetzt in `app/darstellung.py` — dieselbe, die auch die
# Oberfläche benutzt. Vorher war sie hier ausformuliert und in den Vorlagen ein
# zweites Mal (dort falsch): Der Beleg schrieb 2.501,38 €, der Bildschirm
# 2501.38 €. Der Alias bleibt, damit die Aufrufstellen im Modul unverändert
# lesen; `tests/test_geldformat.py` prüft, dass es wirklich dieselbe Funktion ist.
_money = euro


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

    Maßstab ist `TAX_NOTICE`: dieselbe Tabelle, die den Befreiungsgrund liefert
    (AE, E, K, O). Wo ein Grund für die Steuerfreiheit steht, ist eine Steuerzeile
    ein Widerspruch — die Rechnung sagte oben „hier wird keine Umsatzsteuer
    ausgewiesen" und rechnete unten „zzgl. 0 % MwSt. — 0,00 €" vor.

    Es geht dabei nicht um § 14c: ein Betrag von null ist kein unrichtiger
    Steuerausweis. Es geht um Verständlichkeit, und bei AE um mehr als das — der
    Empfänger einer Reverse-Charge-Rechnung muss erkennen, dass ER die Steuer
    schuldet, und keine Zeile lesen, die einen Steuervorgang mit dem Ergebnis null
    nahelegt.
    """
    return getattr(invoice, "tax_category", "S") not in TAX_NOTICE


def _build_item_rows(invoice: Invoice) -> list[list]:
    """Zeilen für die Positionstabelle. Die Beschreibung wird als Paragraph
    ausgegeben, damit sie in ihrer Spalte umbricht statt überzulaufen."""
    desc_style = _item_style()
    mit_steuer = _zeigt_steuer(invoice)
    kopf = ["Pos.", "Beschreibung", "Menge", "Einheit", "Einzelpreis"]
    if mit_steuer:
        kopf.append("MwSt.")
    kopf.append("Betrag")
    rows = [kopf]
    for item in invoice.items:
        zeile = [
            str(item.position),
            Paragraph(_description_markup(item.description), desc_style),
            # NICHT `str(x.normalize())`: das kippt bei durch zehn teilbaren
            # Mengen in die Exponentialform — 120 Stunden stünden als "1.2E+2"
            # auf der Rechnung an den Kunden.
            menge(item.quantity),
            item.unit,
            _money(item.unit_price),
        ]
        if mit_steuer:
            zeile.append(_pct(item.tax_rate))
        zeile.append(_money(item.net_amount))
        rows.append(zeile)
    return rows


def _draft_watermark(font_name: str):
    """`onPage`-Callback, der ein diagonales ENTWURF über die Seite legt.

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
        canvas.drawCentredString(0, 0, "ENTWURF")
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

    # Create custom styles with explicit font names (all our registered embedded fonts)
    normal = ParagraphStyle("Normal", fontName=BODY, fontSize=9, leading=13, textColor=INK)
    small = ParagraphStyle("small", fontName=BODY, fontSize=8, textColor=TEXT_GRAY, leading=11)
    small_right = ParagraphStyle("small_right", fontName=BODY, fontSize=8, textColor=TEXT_GRAY, leading=11, alignment=TA_RIGHT)
    small_bold = ParagraphStyle("small_bold", fontName=BOLD, fontSize=8, textColor=INK)
    right = ParagraphStyle("right", fontName=BODY, fontSize=9, alignment=TA_RIGHT)
    right_bold = ParagraphStyle("right_bold", fontName=BOLD, fontSize=10, alignment=TA_RIGHT, textColor=INK)

    story = []
    W = A4[0] - 4 * cm  # Nutzbreite

    # ── Header ──────────────────────────────────────────────────────────────
    addr_lines = [company.name]
    if company.address_line1:
        addr_lines.append(company.address_line1)
    if company.address_line2:
        addr_lines.append(company.address_line2)
    addr_lines.append(f"{company.zip_code} {company.city}")
    if company.email:
        addr_lines.append(company.email)
    if company.phone:
        addr_lines.append(company.phone)

    contact_text = "<br/>".join(addr_lines)

    tax_info = []
    if company.vat_id:
        tax_info.append(f"USt-IdNr.: {company.vat_id}")
    if company.tax_number:
        tax_info.append(f"Steuernummer: {company.tax_number}")

    # Marken-Stempel: Logo (oben) + Firmenname in Pixelschrift (unten), gerahmt.
    # Pixelschrift + Rahmen statt frei laufender 18pt-Überschrift, die bei langen
    # lange Firmennamen ineinander umbrachen.
    PAD = 10
    brand_fontsize = 8
    brand_style = ParagraphStyle(
        "brand", fontName=PIXEL, fontSize=brand_fontsize, leading=13, textColor=INK
    )
    brand_text = company.name.upper()
    brand_name = Paragraph(brand_text, brand_style)

    logo_img = _logo_flowable()
    # Box eng an den Inhalt: Breite = max(Name, Logo) + Innenabstand, statt fixer
    # Spaltenbreite mit viel Leerraum rechts. +2 Sicherheitspuffer gegen Umbruch
    # bei exakter Textbreite.
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
        # weniger Abstand zwischen Logo und Name
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

    # ── Adressblock Empfänger ────────────────────────────────────────────────
    customer = invoice.customer
    cust_addr = [customer.name]
    if customer.address_line1:
        cust_addr.append(customer.address_line1)
    if customer.address_line2:
        cust_addr.append(customer.address_line2)
    cust_addr.append(f"{customer.zip_code} {customer.city}")
    if customer.country and customer.country != "DE":
        cust_addr.append(customer.country)

    delivery_str = invoice.delivery_date.strftime("%d.%m.%Y") if invoice.delivery_date else "–"
    meta_rows = [
        ("Rechnungsnummer:", invoice.invoice_number),
        ("Rechnungsdatum:", invoice.issue_date.strftime("%d.%m.%Y")),
        ("Leistungsdatum:", delivery_str),
        ("Fälligkeitsdatum:", invoice.due_date.strftime("%d.%m.%Y")),
    ]
    if getattr(customer, "customer_number", None):
        meta_rows.append(("Kundennummer:", customer.customer_number))
    # BT-10: der Kunde ordnet die Rechnung genau hieran seiner Bestellung zu.
    # Sie nur in die XML zu schreiben hieße, sie dem Menschen vorzuenthalten.
    if getattr(invoice, "buyer_reference", None):
        meta_rows.append(("Ihre Referenz:", invoice.buyer_reference))
    if customer.vat_id:
        meta_rows.append(("USt-IdNr. Kunde:", customer.vat_id))

    meta_text = "".join(
        f'<b>{k}</b> {v}<br/>' for k, v in meta_rows
    )

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

    # ── Belegtitel (Pixel) + Nummer (Retro) auf gemeinsamer Grundlinie ────────
    story.append(TitleBand(
        W, _document_title(invoice), invoice.invoice_number,
        title_font=PIXEL, number_font=RETRO,
    ))
    story.append(Spacer(1, 0.5 * cm))

    # ── Positionen ───────────────────────────────────────────────────────────
    # Spaltenbreiten summieren sich exakt auf die Nutzbreite W (17 cm), damit die
    # Tabelle nicht über den rechten Rand hinausläuft. Die Beschreibung bekommt
    # die Restbreite und bricht als Paragraph um (siehe _build_item_rows).
    # Die Steuerspalte (1,4 cm) entfällt bei steuerfreien Belegen (_zeigt_steuer);
    # ihre Breite geht an die Beschreibung. EINE Liste, aus der sich die Restbreite
    # ergibt: zwei getrennte Listen (feste Spalten hier, Breiten dort) würden beim
    # nächsten Eingriff auseinanderlaufen, und die Tabelle liefe stumm über den Rand.
    col_widths = [0.9 * cm, None, 1.3 * cm, 1.3 * cm, 2.3 * cm]
    if _zeigt_steuer(invoice):
        col_widths.append(1.4 * cm)
    col_widths.append(2.6 * cm)
    col_widths[1] = W - sum(w for w in col_widths if w is not None)
    letzte = len(col_widths) - 1

    item_rows = _build_item_rows(invoice)

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
        # Bis zur LETZTEN Spalte, nicht bis zur festen 6: ohne Steuerspalte hat die
        # Tabelle eine Spalte weniger, und eine feste Zahl zeigte dann ins Leere.
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

    # ── Gesetzlicher Steuerhinweis (bei nicht-Inland-Rechnungen) ─────────────
    tax_cat = getattr(invoice, "tax_category", "S")
    if tax_cat in TAX_NOTICE:
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
        story.append(Paragraph(TAX_NOTICE[tax_cat], notice_style))
        story.append(Spacer(1, 0.3 * cm))

    # ── Steueraufstellung + Summen ───────────────────────────────────────────
    from collections import defaultdict
    tax_groups: dict[Decimal, dict] = defaultdict(lambda: {"basis": Decimal("0"), "tax": Decimal("0")})
    for item in invoice.items:
        tax_groups[item.tax_rate]["basis"] += item.net_amount
        tax_groups[item.tax_rate]["tax"] += item.tax_amount

    totals_data = []
    # Der Nettobetrag bleibt auch beim steuerfreien Beleg stehen: § 14 Abs. 4 Nr. 7
    # UStG verlangt das Entgelt, und dass es hier zufällig dem Rechnungsbetrag
    # entspricht, macht es nicht entbehrlich.
    totals_data.append([Paragraph("Nettobetrag", small), Paragraph(_money(invoice.net_total), right)])
    if _zeigt_steuer(invoice):
        for rate in sorted(tax_groups.keys()):
            g = tax_groups[rate]
            label = f"zzgl. {_pct(rate)} MwSt. auf {_money(g['basis'])}"
            totals_data.append([Paragraph(label, small), Paragraph(_money(g["tax"]), right)])
    totals_data.append([
        Paragraph(
            "<b>Gutschriftbetrag</b>" if _ist_gutschrift(invoice) else "<b>Rechnungsbetrag</b>",
            small_bold,
        ),
        Paragraph(f"<b>{_money(invoice.gross_total)}</b>", right_bold)
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
    totals_wrap.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, -1), BODY), ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(totals_wrap)

    # ── Zahlungshinweis ──────────────────────────────────────────────────────
    story.append(Spacer(1, 0.8 * cm))
    payment_text = invoice.payment_terms or (
        "Gutschrift ohne Zahlungsaufforderung." if _ist_gutschrift(invoice) else "Zahlbar ohne Abzug."
    )
    story.append(Paragraph(payment_text, small))
    if company.bank_iban and not _ist_gutschrift(invoice):
        bank_parts = [f"IBAN: {company.bank_iban}"]
        if company.bank_bic:
            bank_parts.append(f"BIC: {company.bank_bic}")
        if company.bank_name:
            bank_parts.append(company.bank_name)
        story.append(Paragraph(" · ".join(bank_parts), small))
        story.append(Paragraph(f"Verwendungszweck: {invoice.invoice_number}", small))

    # ── Freitext / Notiz ─────────────────────────────────────────────────────
    if invoice.notes:
        story.append(Spacer(1, 0.5 * cm))
        story.append(Paragraph(invoice.notes, small))

    # ── Steuerinfo ───────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.8 * cm))
    story.append(HRFlowable(width=W, thickness=0.5, color=BORDER, spaceAfter=6))
    footer_parts = []
    if company.vat_id:
        footer_parts.append(f"USt-IdNr.: {company.vat_id}")
    if company.tax_number:
        footer_parts.append(f"Steuernummer: {company.tax_number}")
    if footer_parts:
        story.append(Paragraph("  ·  ".join(footer_parts), small))

    # ReportLab setzt sonst den nicht eingebetteten Standard-14-Basisfont in die
    # PDF-Präambel (verletzt PDF/A-3). Mit initialFontName=BODY startet der Canvas
    # mit unserer eingebetteten Schrift, sodass kein Standard-14-Font entsteht.
    def _canvasmaker(*args, **kwargs):
        kwargs["initialFontName"] = BODY
        return Canvas(*args, **kwargs)

    if draft:
        wasserzeichen = _draft_watermark(BODY)
        doc.build(story, canvasmaker=_canvasmaker,
                  onFirstPage=wasserzeichen, onLaterPages=wasserzeichen)
    else:
        doc.build(story, canvasmaker=_canvasmaker)
