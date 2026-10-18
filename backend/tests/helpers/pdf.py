"""Gemeinsame PDF-Pruefbausteine: eingebettete Schriften, Text, XMP.

Eine Quelle fuer jedes PDF der Anwendung (Rechnung seit 4, Abrechnungs-
aufstellung seit 7c): Die Pruefung "jede Schrift eingebettet, keine der
Standard-14" ist PDF/A-Pflicht (docs/DEV-DOCU.md, "PDF/A-Schriften
einbetten") und darf an zwei Stellen nicht auseinanderleben.
"""
from pypdf import PdfReader


def schrift_objekte(pfad):
    """Alle Font-Objekte des PDFs, Seite fuer Seite (Muster test_pdf_generator)."""
    reader = PdfReader(str(pfad))
    for page in reader.pages:
        res = page.get("/Resources")
        if not res:
            continue
        fonts = res.get("/Font")
        if not fonts:
            continue
        for ref in fonts.values():
            yield ref.get_object()


def schrift_ist_eingebettet(font_obj) -> bool:
    """True, wenn der FontDescriptor eine FontFile*-Einbettung traegt."""
    fd = font_obj.get("/FontDescriptor")
    if fd is None and "/DescendantFonts" in font_obj:
        desc = font_obj["/DescendantFonts"][0].get_object()
        fd = desc.get("/FontDescriptor")
    if fd is None:
        return False
    fd = fd.get_object()
    return any(k in fd for k in ("/FontFile", "/FontFile2", "/FontFile3"))


def text(pfad) -> str:
    """Text aller Seiten, Whitespace zu einfachen Leerzeichen gefaltet.

    pypdf bricht Zeilen um; eine Assertion soll am Inhalt scheitern
    koennen, nicht am Zeilenfall der Extraktion.
    """
    reader = PdfReader(str(pfad))
    roh = "\n".join(page.extract_text() or "" for page in reader.pages)
    return " ".join(roh.split())


def xmp(pfad) -> str:
    """XMP-Metadaten als Text (pdfaid:part u. a.), Muster test_zugferd_pdf_af."""
    root = PdfReader(str(pfad)).trailer["/Root"]
    meta = root.get("/Metadata")
    assert meta is not None, "PDF hat keine /Metadata (XMP)"
    return meta.get_object().get_data().decode("utf-8", "replace")
