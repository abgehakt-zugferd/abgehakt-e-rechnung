import pytest
from reportlab.pdfbase import pdfmetrics
from app.services import pdf_fonts


def test_register_fonts_returns_logical_names():
    names = pdf_fonts.register_fonts()
    assert names == {
        "body": "DocBody",
        "body_bold": "DocBody-Bold",
        "body_italic": "DocBody-Italic",
        "pixel": "DocPixel",
        "retro": "DocRetro",
    }


def test_registered_body_font_covers_german_glyphs():
    pdf_fonts.register_fonts()
    face = pdfmetrics.getFont("DocBody").face
    for ch in "€äöüß":
        assert face.charToGlyph.get(ord(ch)), f"Glyph fehlt: {ch}"


def test_accent_fonts_are_registered():
    pdf_fonts.register_fonts()
    # getFont wirft KeyError, wenn nicht registriert
    assert pdfmetrics.getFont("DocPixel") is not None
    assert pdfmetrics.getFont("DocRetro") is not None


def test_register_fonts_is_idempotent():
    a = pdf_fonts.register_fonts()
    b = pdf_fonts.register_fonts()
    assert a == b


def test_missing_font_file_raises_clear_error(monkeypatch):
    from pathlib import Path
    monkeypatch.setattr(pdf_fonts, "_registered", False)
    broken = dict(pdf_fonts._FONTS)
    broken["DocPixel"] = Path("/does/not/exist/Nope.ttf")
    monkeypatch.setattr(pdf_fonts, "_FONTS", broken)
    with pytest.raises(FileNotFoundError, match="DocPixel"):
        pdf_fonts.register_fonts()
