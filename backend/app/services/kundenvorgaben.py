"""Vorbelegung eines Rechnungsentwurfs aus dem Kundenstamm (Bauschritt 2a).

Festlegung 15: Kundenvorgaben werden kopiert, nicht gelesen. Diese Funktion ist
die EINE Stelle, die aus Kunde und Leistungszeitraum die Vorbelegung liefert;
Anlegen und erstes Speichern mit Kunde rufen sie auf und muessen die Regeln
(Platzhalter, Reihenfolge) nicht selbst kennen.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.models.customer import Customer

# Platzhalter im Kopf- und Fusstext des Kunden (Entscheidung 5).
PLATZHALTER_LEISTUNGSMONAT = "{leistungsmonat}"


@dataclass(frozen=True)
class Vorbelegung:
    """Werte, die ein neuer Entwurf aus dem Kundenstamm erhaelt.

    kopftext/fusstext tragen den Platzhalter schon ersetzt. zahlungshinweis und
    belegsprache sind nur gesetzt, wenn der Kunde eine Vorgabe traegt; sonst
    None und der Aufrufer verfaehrt wie bisher (Formular, Sprachvorgabe der
    Firma).
    """

    kopftext: str | None
    fusstext: str | None
    zahlungshinweis: str | None
    belegsprache: str | None


def _leistungsmonat(von: date | None, bis: date | None) -> str:
    """MM/JJJJ des Leistungszeitraums; ohne Zeitraum der leere Text.

    Massgeblich ist der Beginn des Zeitraums; fehlt er, das Ende. Ein
    Rechnungsauftrag umfasst ohnehin genau einen Kalendermonat.
    """
    zeitpunkt = von or bis
    if zeitpunkt is None:
        return ""
    return f"{zeitpunkt.month:02d}/{zeitpunkt.year:04d}"


def entwurfs_vorbelegung(
    kunde: Customer | None,
    leistungszeitraum_von: date | None = None,
    leistungszeitraum_bis: date | None = None,
) -> Vorbelegung:
    """Vorbelegung fuer den Entwurf einer Rechnung an diesen Kunden.

    Ohne Leistungszeitraum wird {leistungsmonat} durch einen LEEREN Text ersetzt
    (nicht durch den Roh-Platzhalter belassen): ein gespeicherter Entwurf, in dem
    "{leistungsmonat}" wie Text steht, wuerde unbeanstandet finalisiert und
    erreichte den Kunden. Der leere Monat ist bewusst keine Beanstandung — der
    Nutzer kann den Text im Entwurf bearbeiten, und ohne Zeitraum gibt es nichts,
    was das Programm an seiner Stelle sinvoll einsetzen koennte.
    """
    if kunde is None:
        return Vorbelegung(None, None, None, None)
    monat = _leistungsmonat(leistungszeitraum_von, leistungszeitraum_bis)
    kopftext = kunde.kopftext
    if kopftext is not None:
        kopftext = kopftext.replace(PLATZHALTER_LEISTUNGSMONAT, monat)
    fusstext = kunde.fusstext
    if fusstext is not None:
        fusstext = fusstext.replace(PLATZHALTER_LEISTUNGSMONAT, monat)
    zahlungshinweis = (kunde.zahlungshinweis or "").strip() or None
    belegsprache = (kunde.belegsprache_vorgabe or "").strip() or None
    return Vorbelegung(kopftext, fusstext, zahlungshinweis, belegsprache)
