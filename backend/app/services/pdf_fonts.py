"""
Registriert die für das gebrandete Rechnungs-PDF genutzten Schriften.

- Fließtext/Tabellen: Bitstream Vera (mit ReportLab gebündelt, volle deutsche
  Glyph-Abdeckung inkl. € ä ö ü ß) → garantiert vorhanden & eingebettet.
- Akzente/Überschriften: Press Start 2P (Pixel-Wortmarke/Doctype-Titel) und
  VT323 (Retro-Nummernbadge), vendored unter app/assets/fonts/.

Alle Schriften werden als TTF eingebettet → PDF/A-3-tauglich.
"""
from pathlib import Path
import reportlab
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

_ASSET_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_RL_FONTS = Path(reportlab.__file__).resolve().parent / "fonts"

# logischer Name -> TTF-Datei
_FONTS = {
    "DocBody":        _RL_FONTS / "Vera.ttf",
    "DocBody-Bold":   _RL_FONTS / "VeraBd.ttf",
    "DocBody-Italic": _RL_FONTS / "VeraIt.ttf",
    "DocPixel":       _ASSET_FONTS / "PressStart2P-Regular.ttf",
    "DocRetro":       _ASSET_FONTS / "VT323-Regular.ttf",
}

_registered = False


def register_fonts() -> dict[str, str]:
    """Registriert alle Schriften (idempotent). Gibt logische Namen zurück.

    Registriert die drei Body-Schnitte (Vera) als Font-Family DocBody sowie die
    beiden Akzent-Fonts. Alle als eingebettete TTF → PDF/A-3-tauglich.
    Wirft FileNotFoundError mit klarer Meldung, wenn eine TTF-Datei fehlt.
    """
    global _registered
    if not _registered:
        for name, path in _FONTS.items():
            if not path.exists():
                raise FileNotFoundError(
                    f"Schriftdatei für '{name}' fehlt: {path}. "
                    f"Pixel-Fonts müssen unter {_ASSET_FONTS} liegen "
                    f"(siehe Vendoring-Schritt im Plan)."
                )
            pdfmetrics.registerFont(TTFont(name, str(path)))
        pdfmetrics.registerFontFamily(
            "DocBody",
            normal="DocBody",
            bold="DocBody-Bold",
            italic="DocBody-Italic",
            boldItalic="DocBody-Bold",
        )
        _registered = True
    return {
        "body": "DocBody",
        "body_bold": "DocBody-Bold",
        "body_italic": "DocBody-Italic",
        "pixel": "DocPixel",
        "retro": "DocRetro",
    }
