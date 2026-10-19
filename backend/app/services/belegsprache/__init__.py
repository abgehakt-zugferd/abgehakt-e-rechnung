"""Belegsprache: gespeicherter Sprachcode -> vollstaendige Belegdarstellung.

Reine Darstellungslogik ohne HTTP, Jinja, Datenbank, ReportLab, XML oder Invoice.
`de` und `en` sind die einzigen Codes. Unbekannte Werte fallen nicht auf Deutsch
zurueck: ein fremdsprachiger Beleg wuerde sonst unbemerkt falsch beschriftet.

Formatierung ist zustandsfrei: kein locale.setlocale, keine globale aktuelle
Sprache. Jeder Aufruf von `darstellung(sprache)` liefert einen unveraenderlichen
Datensatz mit eigenen Formatmethoden.
"""

from app.services.belegsprache.bestand import darstellung
from app.services.belegsprache.grundlagen import (
    Belegsprache,
    UnknownDocumentLanguageError,
    dezimal_klartext,
    resolve_belegsprache,
)
from app.services.belegsprache.modell import Belegdarstellung

__all__ = [
    "Belegdarstellung",
    "Belegsprache",
    "UnknownDocumentLanguageError",
    "darstellung",
    "dezimal_klartext",
    "resolve_belegsprache",
]
