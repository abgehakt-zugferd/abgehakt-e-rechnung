"""Spaltenbreiten der Positionstabelle, abgeleitet aus dem Inhalt.

Feste Zentimeter passten nicht: „Stunden“ stand auf einer echten Rechnung
abgeschnitten in der Spalte „Einheit“, und gemessen passten neun von sechzehn
Einheiten, mehrere Spaltenköpfe, vierstellige Mengen und englische Beträge ab fünf
Stellen nicht in ihre Spalte. Jede feste Spalte ist deshalb so breit wie ihr
breitester Text (Kopf fett, Zellen normal) plus Polsterung; die Beschreibung bricht
um und bekommt den Rest.
"""
from reportlab.pdfbase.pdfmetrics import stringWidth


from reportlab.lib.units import cm

BESCHREIBUNG_MIN = 4 * cm


def spaltenbreiten(kopf: list[str], zeilen: list[list], gesamt: float, *,
                   schrift: str, fett: str, groesse: float, polster: float,
                   beschreibung: int = 1) -> list[float]:
    """Breiten in Punkt, Summe = `gesamt`.

    `zeilen` enthält je Zelle einen Text, nur die Beschreibungsspalte nicht: dort
    steht ein umbrechender Paragraph, und sie wird nicht vermessen. Sie bekommt den
    Rest, mindestens `BESCHREIBUNG_MIN`. Reicht der Platz dafür nicht (Beträge im
    Billionenbereich), geben die festen Spalten anteilig nach; ihre Texte stehen
    dann über, die Beschreibung bleibt lesbar.
    """
    breiten: list[float] = []
    for spalte, titel in enumerate(kopf):
        if spalte == beschreibung:
            breiten.append(0.0)
            continue
        noetig = stringWidth(str(titel), fett, groesse)
        for zeile in zeilen:
            noetig = max(noetig, stringWidth(str(zeile[spalte]), schrift, groesse))
        breiten.append(noetig + polster)
    fest = sum(breiten)
    if gesamt - fest < BESCHREIBUNG_MIN:
        faktor = (gesamt - BESCHREIBUNG_MIN) / fest
        breiten = [b * faktor for b in breiten]
    breiten[beschreibung] = gesamt - sum(breiten)
    return breiten
