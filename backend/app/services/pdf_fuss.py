"""Fester Fuß auf jeder Seite des Rechnungs-PDFs, dazu „Seite x von y“.

Vorher stand der Fuß am Ende des Textflusses und damit nur auf der letzten Seite.
Drei Spalten: Firma und Kontakt | Steuernummern und Pflichtangaben | Bank. Die
Höhe wird gemessen, nicht geschätzt: lange Namen und Registerangaben umbrechen, und
der Textfluss muss über dem Fuß enden (`unterer_rand`).

Bei Gutschriften fließt das Geld zum Kunden. Die eigene IBAN im Fuß sähe dann wie
eine Zahlungsaufforderung aus (#18); die Bankspalte bleibt deshalb leer.
"""
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from app.services.adresse import bereinige_adresszeile2
from app.services.bankverbindung import iban_fuer_ausgabe
from app.services.belegsprache import Belegdarstellung
from app.services.iban import IbanProfil
from app.services.pflichtangaben import pflichtangaben

GROESSE = 7
ABSTAND_UNTEN = 1.0 * cm
# Platz zwischen Textfluss und Fuß, darin Trennlinie und Seitenzahl.
LUFT = 0.8 * cm
GRAU = colors.HexColor("#555555")
LINIE = colors.HexColor("#c8c8c8")


class Fuss:
    def __init__(self, company, d: Belegdarstellung, *, schrift: str, breite: float,
                 links: float, mit_bank: bool):
        self._links = links
        self._breite = breite
        stil = ParagraphStyle("fuss", fontName=schrift, fontSize=GROESSE,
                              leading=GROESSE + 2, textColor=GRAU)
        spalten = [_firma(company), _steuer_und_register(company, d), []]
        if mit_bank:
            spalten[2] = _bank(company)
        zellen = [[Paragraph("<br/>".join(escape(z) for z in spalte), stil) for spalte in spalten]]
        self._tabelle = Table(zellen, colWidths=[breite / 3] * 3)
        self._tabelle.setStyle(TableStyle([
            # Ohne eigene Zellschrift setzt ReportLab je Zelle Helvetica, auch wenn
            # ein Paragraph darin steht: nicht eingebettet, also kein PDF/A.
            ("FONTNAME", (0, 0), (-1, -1), schrift),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        _, self.hoehe = self._tabelle.wrap(breite, 1000 * cm)

    @property
    def unterer_rand(self) -> float:
        """bottomMargin des Dokuments: Fuß, Linie und Seitenzahl haben darunter Platz."""
        return ABSTAND_UNTEN + self.hoehe + LUFT

    @property
    def oberkante(self) -> float:
        return ABSTAND_UNTEN + self.hoehe

    def zeichne(self, canvas, _doc=None) -> None:
        canvas.saveState()
        oben = self.oberkante + 4
        canvas.setStrokeColor(LINIE)
        canvas.setLineWidth(0.5)
        canvas.line(self._links, oben, self._links + self._breite, oben)
        self._tabelle.drawOn(canvas, self._links, ABSTAND_UNTEN)
        canvas.restoreState()


def _firma(company) -> list[str]:
    zeilen = [company.name, company.address_line1]
    zusatz = bereinige_adresszeile2(company.name, company.address_line2)
    if zusatz:
        zeilen.append(zusatz)
    zeilen.append(f"{company.zip_code} {company.city}")
    zeilen += [w for w in (company.email, company.phone) if w]
    return [z for z in zeilen if z]


def _steuer_und_register(company, d: Belegdarstellung) -> list[str]:
    zeilen = []
    if company.tax_number:
        zeilen.append(f"{d.label_steuernummer} {company.tax_number}")
    if company.vat_id:
        zeilen.append(f"{d.label_ust_id} {company.vat_id}")
    return zeilen + list(pflichtangaben(company, d.code).zeilen)


def _bank(company) -> list[str]:
    if not company.bank_iban:
        return []
    zeilen = [company.bank_name] if company.bank_name else []
    iban = iban_fuer_ausgabe(company.bank_iban, wer="Firma", profil=IbanProfil.REGISTRY)
    zeilen.append(f"IBAN: {iban}")
    if company.bank_bic:
        zeilen.append(f"BIC: {company.bank_bic}")
    return zeilen


def leinwand(schrift: str, muster: str, fuss: Fuss, *, rechts: float):
    """Canvas-Klasse, die jede Seite mit Fuß und „Seite i von n“ versieht.

    `n` steht erst fest, wenn alle Seiten gesetzt sind: die Seiten werden deshalb
    gesammelt und beim Speichern einmal nachgezeichnet. Die Startschrift bleibt die
    eingebettete Hausschrift; sonst stünde Helvetica als nicht eingebettete
    Standardschrift im PDF/A.
    """
    class _Leinwand(Canvas):
        def __init__(self, *args, **kwargs):
            kwargs["initialFontName"] = schrift
            super().__init__(*args, **kwargs)
            self._seiten: list[dict] = []

        def showPage(self):
            self._seiten.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            gesamt = len(self._seiten)
            for zustand in self._seiten:
                self.__dict__.update(zustand)
                fuss.zeichne(self)
                self.saveState()
                self.setFont(schrift, GROESSE)
                self.setFillColor(GRAU)
                self.drawRightString(rechts, fuss.oberkante + 8,
                                     muster.format(seite=self._pageNumber, gesamt=gesamt))
                self.restoreState()
                super().showPage()
            super().save()

    return _Leinwand
