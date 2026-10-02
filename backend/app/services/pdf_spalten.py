"""Spaltenbreiten der Positionstabelle, abgeleitet aus dem Inhalt.

Feste Zentimeter passten nicht: „Stunden“ stand auf einer echten Rechnung
abgeschnitten in der Spalte „Einheit“, und gemessen passten neun von sechzehn
Einheiten, mehrere Spaltenköpfe, vierstellige Mengen und englische Beträge ab fünf
Stellen nicht in ihre Spalte. Jede feste Spalte ist deshalb so breit wie ihr
breitester Text (Kopf fett, Zellen normal) plus Polsterung; die Beschreibung bricht
um und bekommt den Rest.
"""
from reportlab.pdfbase.pdfmetrics import stringWidth


def spaltenbreiten(kopf: list[str], zeilen: list[list], gesamt: float, *,
                   schrift: str, fett: str, groesse: float, polster: float,
                   beschreibung: int = 1) -> list[float]:
    """Breiten in Punkt, Summe = `gesamt`.

    `zeilen` enthält je Zelle einen Text; die Zelle der Beschreibungsspalte wird
    nicht vermessen (dort steht ein umbrechender Paragraph). Sehr große Beträge
    können die Beschreibung schmal machen; sie wird nie negativ.
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
    breiten[beschreibung] = max(gesamt - sum(breiten), 0.0)
    return breiten
