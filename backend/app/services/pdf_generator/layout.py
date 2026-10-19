"""Layout-Helfer und visuelle Konstanten fuer das Rechnungs-PDF."""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Flowable, Image

from app.config import get_settings
from app.services.pdf_fonts import register_fonts

# ── Firmenlogo ───────────────────────────────────────────────────────────────
# Das Logo gehört der Nutzerin, nicht dem Auslieferungs-Image (#99 §4.3, L4):
# es liegt als `logo.png` im storage-Volume, das pro Installation verschieden ist.
# Ein Logo unter `app/assets/` wäre in JEDEM ausgelieferten Image — die
# Pilotnutzerin bekäme ein fremdes Firmenzeichen auf ihre Rechnung.
LOGO_DATEINAME = "logo.png"
LOGO_TARGET_HEIGHT = 30    # pt — Zielhöhe im Header
LOGO_MAX_WIDTH = 120       # pt — Deckel, damit eine Wortmarke den Header nicht sprengt


TABELLE_GROESSE = 8.5
SUMMEN_BREITE = 8 * cm
QR_KANTE = 2.8 * cm
TABELLE_POLSTER = 4


INK = colors.HexColor("#1a1a2e")          # Fließtext/Überschriften
GOLD = colors.HexColor("#9c7a00")         # print-sicheres Dunkelgold (Linien/Akzente)
GOLD_TINT = colors.HexColor("#f4eeda")    # sehr helle Gold-Tönung (Zeilen/Band)
BORDER = colors.HexColor("#d9cfa6")       # warme, helle Rasterlinie
TEXT_GRAY = colors.HexColor("#5b5b66")    # Sekundärtext, druckkontraststark


def logo_path() -> Path | None:
    """Pfad zum Firmenlogo im storage-Volume, oder None wenn keines hinterlegt ist."""
    pfad = get_settings().storage_path / LOGO_DATEINAME
    return pfad if pfad.exists() else None


def logo_flowable():
    """Passend skaliertes Image-Flowable des Firmenlogos, oder None ohne Logo.

    Skaliert auf Zielhöhe, deckelt aber die Breite: hoch/schmale Logos treffen die
    Zielhöhe, breite Wortmarken laufen sonst quer durch den Header.
    """
    path = logo_path()
    if path is None:
        return None
    iw, ih = ImageReader(str(path)).getSize()
    h = LOGO_TARGET_HEIGHT
    w = h * iw / ih
    if w > LOGO_MAX_WIDTH:
        w = LOGO_MAX_WIDTH
        h = w * ih / iw
    return Image(str(path), width=w, height=h)


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

        # Lange Belegtitel (insbesondere der englische 389-Titel) dürfen die
        # rechtsbündige Nummer nicht überdrucken. Den Platz an der tatsächlich
        # gezeichneten Nummer messen, statt je Belegart Schriftgrößen zu pflegen.
        nummer_breite = pdfmetrics.stringWidth(self.number, self.number_font, self.number_size)
        titel_breite = pdfmetrics.stringWidth(self.title, self.title_font, self.title_size)
        platz = self.width - 2 * self.pad - nummer_breite - 8
        titel_groesse = self.title_size * min(1, max(1, platz) / max(1, titel_breite))
        c.setFillColor(self.title_color)
        c.setFont(self.title_font, titel_groesse)
        c.drawString(self.pad, baseline, self.title)

        c.setFillColor(self.number_color)
        c.setFont(self.number_font, self.number_size)
        c.drawRightString(self.width - self.pad, baseline, self.number)


def item_style():
    """Absatzstil für umbrechende Positionsbeschreibungen."""
    fonts = register_fonts()
    return ParagraphStyle(
        "item_desc", fontName=fonts["body"], fontSize=8.5, leading=10.5, textColor=INK
    )


def description_markup(text: str) -> str:
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


def draft_watermark(font_name: str, text: str):
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
