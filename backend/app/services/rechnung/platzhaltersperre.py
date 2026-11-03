"""Platzhaltersperre (#270): Kopf- oder Fußtext trägt noch ein Zeichen für „hier setzt der Mensch ein“."""
import re

from app.models.invoice import Invoice

# Übergabeformat § 8a, Schreibweise <M>, <MM/JJJJ>, <nr>. Das Format legt keine
# Form fest, nur diese Beispiele; das Muster ist die Festlegung dieser Sperre:
# spitze Klammer auf, 1 bis 16 Zeichen ohne Klammern, das erste kein Leerraum,
# spitze Klammer zu. „Menge < 5“, „a < b > c“ (Leerraum nach der Klammer),
# „weniger als <10 €“ (keine schließende Klammer) und „<>“ sperren nicht.
PLATZHALTER_MUSTER = re.compile(r"<[^<>\s][^<>]{0,15}>")

_FELDER = (("kopftext", "Kopftext"), ("fusstext", "Fußtext"))


def platzhalter_befunde(invoice: Invoice) -> list[str]:
    """Meldungen je Feld mit Platzhalter, in Feldreihenfolge; leer, wenn keiner da ist."""
    befunde = []
    for attribut, bezeichnung in _FELDER:
        treffer = PLATZHALTER_MUSTER.search(getattr(invoice, attribut) or "")
        if treffer:
            befunde.append(
                f"{bezeichnung} enthält noch den Platzhalter {treffer.group(0)}")
    return befunde
