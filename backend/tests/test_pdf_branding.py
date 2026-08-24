"""Tests für das Branding im Rechnungs-PDF.

Deckt ab:
- das Firmenlogo kommt aus dem storage-Volume, nicht aus dem Image (#99 §4.3)
- Belegtitel + Rechnungsnummer auf EINER gemeinsamen Grundlinie (TitleBand)
- lange Positionsbeschreibungen brechen um (kein Überlauf über die Spalte)
- ein vorhandenes Logo wird als Bild ins PDF eingebettet
"""
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.config import get_settings
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator
from app.services.pdf_generator import (
    LOGO_MAX_WIDTH,
    LOGO_TARGET_HEIGHT,
    TitleBand,
    _logo_flowable,
    _logo_path,
    _build_item_rows,
)


# ── Logo: Nutzerkonfiguration im storage-Volume, kein Repo-Asset ─────────────

def _png(pfad, breite, hoehe):
    """Minimales, gültiges Graustufen-PNG in der gewünschten Pixelgröße.

    Von Hand aus stdlib (zlib/struct) statt über reportlab.renderPM: das Image
    hat kein rlPyCairo-Backend, `renderPM` wirft dort einen RenderPMError.
    """
    import struct
    import zlib

    def chunk(typ, daten):
        return (struct.pack(">I", len(daten)) + typ + daten
                + struct.pack(">I", zlib.crc32(typ + daten) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", breite, hoehe, 8, 0, 0, 0, 0)  # 8 bit, Graustufen
    roh = b"".join(b"\x00" + b"\xff" * breite for _ in range(hoehe))  # Filter 0 je Zeile
    pfad.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", zlib.compress(roh)) + chunk(b"IEND", b""))
    return pfad


@pytest.fixture
def storage(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "storage_path", tmp_path)
    return tmp_path


def test_logo_liegt_im_storage_nicht_im_image(storage):
    """Das Logo gehört der Nutzerin, nicht dem Auslieferungs-Image. Läge es unter
    `app/assets/`, trüge jedes ausgelieferte Image ein fremdes Logo (#99 L4)."""
    _png(storage / "logo.png", 40, 40)

    pfad = _logo_path()

    assert pfad == storage / "logo.png"
    assert "assets" not in str(pfad)


def test_ohne_logodatei_kein_logo(storage):
    """Frische Installation: es gibt keine Logodatei — das darf kein Fehler sein."""
    assert _logo_path() is None
    assert _logo_flowable() is None


def test_pdf_ohne_logodatei_wird_erzeugt(storage):
    """Ohne Logo und ohne EPC-QR (keine IBAN) bleibt das PDF bildfrei."""
    out = storage / "inv.pdf"
    company = _company()
    company.bank_iban = None
    company.bank_bic = None
    pdf_generator.generate_pdf(_invoice(), company, out)
    assert not _has_image_xobject(PdfReader(str(out))), \
        "Ohne Logodatei und ohne QR darf kein Bild im PDF stehen"


def test_pdf_bettet_vorhandenes_logo_ein(storage):
    _png(storage / "logo.png", 40, 40)
    out = storage / "inv.pdf"
    pdf_generator.generate_pdf(_invoice(), _company(), out)
    assert _has_image_xobject(PdfReader(str(out))), "Logo-Bild fehlt im PDF"


def test_hohes_logo_wird_auf_zielhoehe_skaliert(storage):
    _png(storage / "logo.png", 100, 200)   # hoch/schmal

    img = _logo_flowable()

    assert img.drawHeight == pytest.approx(LOGO_TARGET_HEIGHT)
    assert img.drawWidth == pytest.approx(LOGO_TARGET_HEIGHT * 100 / 200)


def test_breites_logo_wird_auf_maximalbreite_begrenzt(storage):
    """Eine Wortmarke (breit/flach) auf Zielhöhe skaliert wäre viel zu breit und
    schöbe den Firmenblock aus dem Header — deshalb deckelt die Breite."""
    _png(storage / "logo.png", 1000, 100)  # breit/flach

    img = _logo_flowable()

    assert img.drawWidth == pytest.approx(LOGO_MAX_WIDTH)
    assert img.drawHeight == pytest.approx(LOGO_MAX_WIDTH * 100 / 1000)
    assert img.drawHeight <= LOGO_TARGET_HEIGHT


# ── TitleBand: gemeinsame Grundlinie ─────────────────────────────────────────

class _RecordingCanvas:
    """Minimaler Canvas-Stub, der nur die Textaufrufe mitschreibt."""

    def __init__(self):
        self.texts = []  # (align, x, y, text)

    def setFillColor(self, *a, **k):
        pass

    def setStrokeColor(self, *a, **k):
        pass

    def setLineWidth(self, *a, **k):
        pass

    def rect(self, *a, **k):
        pass

    def setFont(self, *a, **k):
        pass

    def drawString(self, x, y, text):
        self.texts.append(("L", x, y, text))

    def drawRightString(self, x, y, text):
        self.texts.append(("R", x, y, text))


def test_title_band_draws_title_and_number_on_same_baseline():
    band = TitleBand(400, "RECHNUNG", "RE-2026-042",
                     title_font="DocPixel", number_font="DocRetro")
    band.wrap(400, 100)
    rc = _RecordingCanvas()
    band.canv = rc
    band.draw()

    assert len(rc.texts) == 2, "Titel und Nummer müssen genau einmal gezeichnet werden"
    ys = [t[2] for t in rc.texts]
    assert ys[0] == ys[1], f"Grundlinien weichen ab: {ys}"
    rendered = {t[3] for t in rc.texts}
    assert rendered == {"RECHNUNG", "RE-2026-042"}


def test_title_band_number_is_right_aligned():
    band = TitleBand(400, "RECHNUNG", "RE-2026-042",
                     title_font="DocPixel", number_font="DocRetro")
    band.wrap(400, 100)
    rc = _RecordingCanvas()
    band.canv = rc
    band.draw()
    by_text = {t[3]: t for t in rc.texts}
    assert by_text["RECHNUNG"][0] == "L"
    assert by_text["RE-2026-042"][0] == "R"


# ── Positionsbeschreibungen brechen um ───────────────────────────────────────

def _company():
    return Company(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", email="info@example.de", phone="+49 111",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE00123456780000000000", bank_bic="ABCDDEFF", bank_name="Testbank",
    )


def _invoice(description="Beratungsleistung"):
    cust = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                    zip_code="10115", city="Berlin", country="DE")
    item = InvoiceItem(position=1, description=description, quantity=Decimal("2"),
                       unit="Std", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
                       net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"))
    inv = Invoice(invoice_number="RE-2026-042", issue_date=date(2026, 7, 8),
                  delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22),
                  currency="EUR", net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"), tax_category="S",
                  payment_terms="Zahlbar innerhalb 14 Tagen.", notes="")
    inv.customer = cust
    inv.items = [item]
    return inv


def test_item_description_is_wrapping_paragraph():
    """Beschreibungen sind Paragraphs (umbruchfähig), keine rohen Strings —
    rohe Strings laufen in ReportLab über die Spalte hinaus."""
    from reportlab.platypus import Paragraph
    long_desc = "Workshop E-Rechnung / ZUGFeRD (Tagespauschale, inkl. Nachbereitung)"
    rows = _build_item_rows(_invoice(description=long_desc))
    # rows[0] ist der Header; rows[1] die erste Position
    description_cell = rows[1][1]
    assert isinstance(description_cell, Paragraph), \
        "Beschreibung muss ein Paragraph sein, damit sie in der Spalte umbricht"


# ── Logo-Einbettung ins PDF ──────────────────────────────────────────────────

def _has_image_xobject(reader):
    for page in reader.pages:
        res = page.get("/Resources")
        if not res:
            continue
        xobj = res.get("/XObject")
        if not xobj:
            continue
        for ref in xobj.values():
            obj = ref.get_object()
            if obj.get("/Subtype") == "/Image":
                return True
    return False


