"""Laenderliste fuer die Landesauswahl in den Formularen (#75).

Bis hierher schrieben die drei Formulare mit Landfeld (Kunde, Einstellungen,
Einrichtung) ihre Optionen selbst aus und kannten nur DE, AT, CH und US: ein
Kunde in Finnland liess sich ueber die Oberflaeche nicht anlegen. Wie bei
`branding` und `darstellung` gilt: jeder Router erzeugt sein eigenes
Jinja-Environment, es gibt keinen gemeinsamen Context-Processor. Deshalb
steht die Liste genau einmal hier, und `registriere_laender_globals` gibt sie
je Instanz in die Environments der drei Router, die ein Landfeld rendern.

Gespeichert wird der ISO-3166-1-alpha-2-Code (`String(2)` am Modell); er
laeuft unveraendert in `ram:CountryID` der ZUGFeRD-XML. Griechenland traegt
hier `GR` (ISO); dass VIES Griechenland als `EL` kennt, bildet allein
`services/ust_id_pruefung._VIES_LAENDER` ab, diese Abbildung wird hier nicht
verdoppelt.

Reihenfolge: DE zuerst (Regelfall der Installationen), danach alphabetisch
nach deutschem Namen. Wache: tests/test_laender.py.
"""
from fastapi.templating import Jinja2Templates

LAENDER: tuple[tuple[str, str], ...] = (
    ("DE", "Deutschland"),
    ("AL", "Albanien"),
    ("AD", "Andorra"),
    ("BY", "Belarus"),
    ("BE", "Belgien"),
    ("BA", "Bosnien und Herzegowina"),
    ("BG", "Bulgarien"),
    ("DK", "Dänemark"),
    ("EE", "Estland"),
    ("FI", "Finnland"),
    ("FR", "Frankreich"),
    ("GR", "Griechenland"),
    ("IE", "Irland"),
    ("IS", "Island"),
    ("IT", "Italien"),
    ("HR", "Kroatien"),
    ("LV", "Lettland"),
    ("LI", "Liechtenstein"),
    ("LT", "Litauen"),
    ("LU", "Luxemburg"),
    ("MT", "Malta"),
    ("MD", "Moldau"),
    ("MC", "Monaco"),
    ("ME", "Montenegro"),
    ("NL", "Niederlande"),
    ("MK", "Nordmazedonien"),
    ("NO", "Norwegen"),
    ("AT", "Österreich"),
    ("PL", "Polen"),
    ("PT", "Portugal"),
    ("RO", "Rumänien"),
    ("RU", "Russland"),
    ("SM", "San Marino"),
    ("SE", "Schweden"),
    ("CH", "Schweiz"),
    ("RS", "Serbien"),
    ("SK", "Slowakei"),
    ("SI", "Slowenien"),
    ("ES", "Spanien"),
    ("CZ", "Tschechien"),
    ("TR", "Türkei"),
    ("UA", "Ukraine"),
    ("HU", "Ungarn"),
    ("VA", "Vatikanstadt"),
    ("US", "Vereinigte Staaten"),
    ("GB", "Vereinigtes Königreich"),
    ("CY", "Zypern"),
)

EU_LAENDER: frozenset[str] = frozenset({
    "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR",
    "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "AT", "PL", "PT", "RO",
    "SE", "SI", "SK",
})


def ist_eu(code: str) -> bool:
    return code in EU_LAENDER


def registriere_laender_globals(templates: Jinja2Templates) -> None:
    """Macht `LAENDER` und `ist_eu` in einem Jinja-Environment verfügbar.

    Muss JEDE Instanz einzeln bekommen, die ein Landfeld rendert (Kunden,
    Einstellungen, Einrichtung) — dieselbe Lage wie bei
    `branding.register_branding_globals`. Ein hier vergessener Router fällt
    nicht beim Start auf, sondern erst beim Aufruf seiner Seite.
    """
    templates.env.globals["LAENDER"] = LAENDER
    templates.env.globals["ist_eu"] = ist_eu
