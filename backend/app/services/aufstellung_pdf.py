"""Das sichtbare PDF der Abrechnungsaufstellung (§ 8b, Bauschritt 7c).

KEINE Rechnung (Entscheidung 8): kein ZUGFeRD, kein Mustang, kein
Steuerhinweis, kein Zahlungsblock mit QR-Code. Deshalb kein Weg ueber
pdf_generator — der waere Rechnung durch und durch. Geteilt werden die
Pflichten, nicht die Maschinerie: eingebettete Schriften (pdf_fonts,
canvasmaker mit initialFontName und FONTNAME in jeder TableStyle —
docs/DEV-DOCU.md, „PDF/A-Schriften einbetten“), der feste Fuß mit
Pflichtangaben und „Seite x von y“ (pdf_fuss) und die Farbe des Hauses
(pdf_generator). Die PDF/A-Hebung haengt das Finalisieren hinten an
(aufstellung_finalisieren).
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.adresse import bereinige_adresszeile2
from app.services.belegrollen import besetzung
from app.services.belegsprache import (
    Belegdarstellung,
    darstellung,
    resolve_belegsprache,
)
from app.services.pdf_fuss import Fuss, leinwand
from app.services.pdf_fonts import register_fonts
from app.services.pdf_generator import INK, TEXT_GRAY, TitleBand

# Wie beim Rechnungs-PDF: Textfluss zwischen 2 cm-Raendern.
_RAND = 2 * cm
_BREITE = A4[0] - 2 * _RAND


def erzeuge_pdf(aufstellung, company, ziel: Path) -> None:
    """Schreibt das sichtbare PDF der Aufstellung nach `ziel`.

    Fail-closed wie generate_pdf: Ohne Aufstellung, Firma oder Kunden kein
    PDF — ein Beleg ohne Anschrift ist kein Beleg.
    """
    if not aufstellung:
        raise ValueError("Aufstellung darf nicht None sein")
    if not company:
        raise ValueError("Firmendaten dürfen nicht None sein")
    if not aufstellung.customer:
        raise ValueError("Aufstellung hat keinen Kunden zugeordnet")

    d = _darstellung(aufstellung)
    fonts = register_fonts()
    schrift = fonts["body"]

    # Der feste Fuß (pdf_fuss) gilt auch hier: Pflichtangaben der Firma auf
    # JEDEM Geschaeftsbrief. Ohne Bankspalte: Die Aufstellung meldet eine
    # Zahlung, die schon stattfand (zahlungsnummer/zahlungsdatum); die eigene
    # IBAN waere eine Zahlungsaufforderung, die niemandem zusteht — dieselbe
    # Begruendung wie bei der Gutschrift (#18).
    rollen = besetzung(aufstellung, company, aufstellung.customer)
    fuss = Fuss(company, d, rollen=rollen, schrift=schrift,
                breite=_BREITE, links=_RAND, mit_bank=False)
    doc = SimpleDocTemplate(
        str(ziel), pagesize=A4,
        leftMargin=_RAND, rightMargin=_RAND, topMargin=_RAND,
        bottomMargin=fuss.unterer_rand,
    )
    story = _story(aufstellung, d, fonts, rollen)
    doc.build(story, canvasmaker=leinwand(schrift, d.seite_muster, fuss,
                                          rechts=A4[0] - _RAND))


def _darstellung(aufstellung) -> Belegdarstellung:
    """Sprache der Aufstellung: die Vorgabe am Kunden, ohne Vorgabe Deutsch.

    Ein eigenes Sprachfeld hat die Aufstellung nicht (7a): Sie entsteht aus
    einem § 8b-Auftrag, der keine Sprache traegt. Empfaenger ist der Auszahler
    hinter der partner_id — dessen Erwartung steht als Vorgabe am Kunden.
    Ein ungueltiger gespeicherter Wert wirft (resolve_belegsprache), er
    darf nicht still auf Deutsch fallen.
    """
    roh = getattr(aufstellung.customer, "belegsprache_vorgabe", None) or "de"
    return darstellung(resolve_belegsprache(roh))


def _story(aufstellung, d, fonts, rollen):
    story = [TitleBand(_BREITE, d.titel_aufstellung, aufstellung.nummer,
                      title_font=fonts["pixel"], number_font=fonts["retro"]),
             Spacer(1, 0.6 * cm)]
    story.append(_parteien(d, fonts, rollen))
    story.append(Spacer(1, 0.6 * cm))
    story.append(_kopf(aufstellung, d, fonts))
    story.append(Spacer(1, 0.6 * cm))
    story.append(_betraege(aufstellung, d, fonts))
    story.append(Spacer(1, 0.6 * cm))
    story.extend(_anlagen(aufstellung, d, fonts))
    story.append(Spacer(1, 0.6 * cm))
    story.append(_keine_rechnung_hinweis(d, fonts))
    return story


def _adresse(partei) -> list[str]:
    """Anschrift einer Partei als Zeilen (Muster pdf_generator: Zeile 2
    bereinigt, Land nur wenn es das Inland ueberschreitet)."""
    zeilen = [partei.name]
    if partei.address_line1:
        zeilen.append(partei.address_line1)
    zusatz = bereinige_adresszeile2(partei.name, partei.address_line2)
    if zusatz:
        zeilen.append(zusatz)
    zeilen.append(f"{partei.zip_code} {partei.city}")
    if partei.country and partei.country != "DE":
        zeilen.append(partei.country)
    return [z for z in zeilen if z]


def _parteien(d, fonts, rollen) -> Table:
    """Aussteller (eigene Firma) und Auszahler (Kunde) mit Anschrift."""
    kopf = ParagraphStyle("parteien_kopf", fontName=fonts["body_bold"],
                          fontSize=8, textColor=TEXT_GRAY)
    stil = ParagraphStyle("parteien", fontName=fonts["body"], fontSize=9,
                          leading=13, textColor=INK)
    zeilen = [
        [Paragraph(escape(d.label_aussteller), kopf),
         Paragraph(escape(d.label_auszahler), kopf)],
        [Paragraph("<br/>".join(escape(z) for z in _adresse(rollen.verkaeufer)), stil),
         Paragraph("<br/>".join(escape(z) for z in _adresse(rollen.erwerber)), stil)],
    ]
    tabelle = Table(zeilen, colWidths=[_BREITE / 2] * 2)
    tabelle.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), fonts["body"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
    ]))
    return tabelle


def _kopf(aufstellung, d, fonts) -> Table:
    """Nummer, Ausstellungsdatum, Leistungsmonat, Zahlung des Auszahlers.

    Das Ausstellungsdatum steht erst ab dem Stellen auf dem Beleg (Guard);
    im Entwurf fehlt die Zeile, statt eines erfundenen Datums.
    """
    zeilen = [(d.label_aufstellungsnummer, aufstellung.nummer)]
    if aufstellung.ausstellungsdatum is not None:
        zeilen.append((d.label_ausstellungsdatum,
                       d.format_datum(aufstellung.ausstellungsdatum)))
    zeilen.append((d.label_leistungsmonat,
                   aufstellung.leistung_von.strftime("%m/%Y")))
    zeilen.append((d.label_zahlungsnummer, aufstellung.zahlungsnummer))
    zeilen.append((d.label_zahlungsdatum, d.format_datum(aufstellung.zahlungsdatum)))
    stil = ParagraphStyle("kopf", fontName=fonts["body"], fontSize=8,
                          leading=11, textColor=TEXT_GRAY)
    zellen = [[Paragraph(f"<b>{escape(k)}</b>", stil), Paragraph(escape(str(v)), stil)]
              for k, v in zeilen]
    tabelle = Table(zellen, colWidths=[_BREITE * 0.3, _BREITE * 0.7])
    tabelle.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), fonts["body"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    return tabelle


def _betraege(aufstellung, d, fonts) -> Table:
    """Brutto, Quellensteuer, Netto in der Berichtswaehrung; bei Fremd-
    waehrung Kurs und Zahlbetrag in EUR, beides NUR aus dem Auftrag
    (Festlegung 21: Abgehakt rechnet nichts um, es zeigt)."""
    w = aufstellung.waehrung
    klein = ParagraphStyle("summe", fontName=fonts["body"], fontSize=8, textColor=INK)
    rechts = ParagraphStyle("summe_rechts", fontName=fonts["body"], fontSize=8,
                            alignment=TA_RIGHT, textColor=INK)
    fett = ParagraphStyle("summe_fett", fontName=fonts["body_bold"], fontSize=9,
                         textColor=INK)
    rechts_fett = ParagraphStyle("summe_rechts_fett", fontName=fonts["body_bold"],
                                 fontSize=9, alignment=TA_RIGHT, textColor=INK)
    zeilen = [
        [Paragraph(escape(d.label_brutto), klein),
         Paragraph(d.format_betrag(aufstellung.brutto, w), rechts)],
        [Paragraph(escape(d.label_quellensteuer), klein),
         Paragraph(d.format_betrag(aufstellung.quellensteuer, w), rechts)],
    ]
    if aufstellung.kurs is not None:
        # format_menge nimmt keine Rundung vor: so viele Stellen, wie der
        # Auftrag nannte (de mit Komma, en mit Punkt).
        zeilen.append([Paragraph(escape(d.label_kurs), klein),
                       Paragraph(d.format_menge(aufstellung.kurs), rechts)])
    if aufstellung.zahlbetrag_eur is not None:
        zeilen.append([Paragraph(escape(d.label_zahlbetrag), klein),
                       Paragraph(d.format_betrag(aufstellung.zahlbetrag_eur, "EUR"),
                                 rechts)])
    zeilen.append([Paragraph(f"<b>{d.label_netto}</b>", fett),
                   Paragraph(f"<b>{d.format_betrag(aufstellung.netto, w)}</b>",
                             rechts_fett)])
    tabelle = Table(zeilen, colWidths=[_BREITE * 0.7, _BREITE * 0.3])
    tabelle.hAlign = "RIGHT"
    tabelle.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), fonts["body"]),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEABOVE", (0, -1), (-1, -1), 1, INK),
    ]))
    return tabelle


def _anlagen(aufstellung, d, fonts) -> list:
    """Je Anlage Quelle, Dateiname und Groesse, darunter der volle SHA-256.

    Der Hash ist der Nachweis der byte-gleichen Kopie — halb gedruckt waere
    er eine Behauptung. VT323 ist die einzige mitgelieferte MONOSPACE-Schrift
    (pdf_fonts): Hex bleibt lesbar als das, was es ist. Als Paragraph bricht
    er in der Zeile, statt ueberzulaufen (rohe Tabellenzellen brechen nie).
    """
    if not aufstellung.anlagen:
        return []
    kopf = ParagraphStyle("anlage_kopf", fontName=fonts["body_bold"], fontSize=8,
                          textColor=INK)
    stil = ParagraphStyle("anlage", fontName=fonts["body"], fontSize=8,
                          leading=10, textColor=INK)
    hash_stil = ParagraphStyle("anlage_sha", fontName=fonts["retro"], fontSize=8,
                               leading=10, textColor=INK)
    zeilen = [[d.label_quelle, d.label_dateiname, d.label_groesse_bytes]]
    sha_zeilen = []
    for anlage in aufstellung.anlagen:
        zeilen.append([
            Paragraph(escape(d.anlagenquelle(anlage.quelle)), stil),
            Paragraph(escape(anlage.dateiname), stil),
            Paragraph(d.format_menge(anlage.groesse), stil),
        ])
        sha_zeilen.append(len(zeilen))
        zeilen.append([Paragraph(f"{d.label_sha256}: {anlage.sha256}", hash_stil),
                       "", ""])
    tabelle = Table(zeilen, colWidths=[4 * cm, 6 * cm, _BREITE - 10 * cm])
    tabelle.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), fonts["body"]),
        ("FONTNAME", (0, 0), (-1, 0), fonts["body_bold"]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, INK),
    ] + [("SPAN", (0, r), (-1, r)) for r in sha_zeilen]))
    return [Paragraph(f"<b>{escape(d.label_anlagen)}</b>", kopf),
            Spacer(1, 0.2 * cm), tabelle]


def _keine_rechnung_hinweis(d, fonts) -> Paragraph:
    """Die Abgrenzung nach § 14 UStG: Wer die Aufstellung liest, soll nicht
    nach einer Steuer oder einer Rechnungsnummer suchen, die es nicht gibt."""
    stil = ParagraphStyle("keine_rechnung", fontName=fonts["body_italic"],
                          fontSize=8, leading=12, textColor=TEXT_GRAY)
    return Paragraph(escape(d.hinweis_keine_rechnung), stil)
