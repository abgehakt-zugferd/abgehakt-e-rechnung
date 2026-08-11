"""
Konvertiert ein normales PDF (ReportLab) in ein PDF/A-3 mittels Ghostscript.

Warum nötig: Mustangs `combine` nutzt `ZUGFeRDExporterFromPDFA`, der die
PDF/A-Konformitätsstufe aus dem XMP-Feld `pdfaid:part` liest. Ein ReportLab-PDF
hat weder XMP-Metadaten noch einen OutputIntent → `PDF-A version not supported`.
Ghostscript (`-dPDFA=3`) ergänzt XMP + sRGB-OutputIntent und macht das PDF
PDF/A-3-tauglich, sodass Mustang die ZUGFeRD-XML danach einbetten kann.

Das sRGB-ICC-Profil liegt dem Ghostscript-Paket bei
(`/usr/share/ghostscript/*/iccprofiles/srgb.icc`) — nicht vendored.
"""
import glob
import shutil
import subprocess
import tempfile
from pathlib import Path

_ICC_GLOBS = (
    "/usr/share/ghostscript/*/iccprofiles/srgb.icc",
    "/usr/share/color/icc/ghostscript/srgb.icc",
)


def _find_icc() -> str | None:
    for pattern in _ICC_GLOBS:
        for path in sorted(glob.glob(pattern)):
            if Path(path).exists():
                return path
    return None


def gs_available() -> bool:
    """True, wenn Ghostscript UND ein sRGB-ICC-Profil verfügbar sind."""
    return shutil.which("gs") is not None and _find_icc() is not None


def to_pdfa3(pdf_in: Path, pdf_out: Path, title: str = "") -> bool:
    """Hebt `pdf_in` auf PDF/A-3 und schreibt nach `pdf_out`.

    Gibt True nur zurück, wenn Ghostscript rc=0 liefert UND die Ausgabedatei
    tatsächlich entstanden ist.
    """
    icc = _find_icc()
    if icc is None:
        return False
    src = Path(pdf_in)
    if not src.exists():
        return False

    out = Path(pdf_out)
    out.unlink(missing_ok=True)

    with tempfile.TemporaryDirectory() as td:
        def_ps = Path(td) / "PDFA_def.ps"
        def_ps.write_text(_pdfa_def(icc, title), encoding="utf-8")
        cmd = [
            "gs", "-dPDFA=3", "-dBATCH", "-dNOPAUSE", "-dNOOUTERSAVE",
            "-sColorConversionStrategy=RGB", "-sDEVICE=pdfwrite",
            "-dPDFACompatibilityPolicy=1", f"-sOutputFile={out}",
            str(def_ps), str(src),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        except subprocess.TimeoutExpired:
            # Wie bei Mustang: ein ausgelasteter Rechner ist ein Fehlschlag, kein
            # Absturz. Durchfliegend würde die Ausnahme im Finalisieren das
            # Aufräumen und den Rollback überspringen.
            return False

    return result.returncode == 0 and out.exists()


def _ps_escape(text: str) -> str:
    # Steuerzeichen (u.a. Zeilenumbrüche) entfernen — sie würden das
    # PS-String-Literal aufbrechen. Backslash/Klammern maskieren.
    cleaned = "".join(ch for ch in text if ch >= " ")
    return cleaned.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _pdfa_def(icc: str, title: str) -> str:
    """PostScript-Präambel: definiert den sRGB-OutputIntent für PDF/A."""
    return (
        "%!\n"
        f"[ /Title ({_ps_escape(title)}) /DOCINFO pdfmark\n"
        "[ /_objdef {icc_PDFA} /type /stream /OBJ pdfmark\n"
        "[ {icc_PDFA} << /N 3 >> /PUT pdfmark\n"
        f"[ {{icc_PDFA}} ({icc}) (r) file /PUT pdfmark\n"
        "[ /_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark\n"
        "[ {OutputIntent_PDFA} << /Type /OutputIntent /S /GTS_PDFA1"
        " /DestOutputProfile {icc_PDFA} /OutputConditionIdentifier (sRGB) >> /PUT pdfmark\n"
        "[ {Catalog} << /OutputIntents [ {OutputIntent_PDFA} ] >> /PUT pdfmark\n"
    )
