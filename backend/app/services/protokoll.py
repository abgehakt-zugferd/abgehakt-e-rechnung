"""Die Protokollfassung, mit der diese Anwendung rechnet (abgehakt#72).

`format_version` auf einem Beleg sagt, nach welchen Regeln DIESER Beleg gebaut
ist. Sie beantwortet nicht die Frage, die dreimal im Jahr gestellt wird: rechnen
die beteiligten Anwendungen gerade mit derselben Fassung? Dafuer stehen die
Konstanten hier, und sie stehen NEBEN der Programmfassung: wann diese Anwendung
gebaut wurde, sagt ueber das Protokoll nichts.

Massgeblich ist `protokoll.json` im Ordner der Uebergabepapiere (UEBERGABEFORMAT
§ 14), nicht dieser Quelltext. Drei Quelltexte waeren drei Staende; die Datei ist
einer. Dass diese Konstanten ihr folgen, misst
`tests/vektoren/test_protokoll_vektoren.py`, und der Test wird
rot, sobald das Protokoll sich bewegt hat und diese Anwendung nicht. Mehr
Abstimmung gibt es nicht: zur Laufzeit fragen die Anwendungen einander nichts,
der Belegordner bleibt die einzige Verbindung im Betrieb.
"""

import re
from typing import Optional

PROTOKOLL_VERSION = "1.6"

AKZEPTIERTE_FASSUNGEN = ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6")

ABGELEHNT_AB_MAJOR = 2

NUTZLAST_ARTEN = ("erloesmeldung", "abrechnungsauftrag", "quittung")

# Geschlossener Wertevorrat. Ein selbst erfundenes Wort gibt es nicht: eine
# Quittung, deren Code der Leser nicht kennt, ist wieder "ungueltiges Dokument".
BEFUNDCODES = frozenset({
    "SIGNATUR_UNGUELTIG",
    "SCHLUESSEL_UNBEKANNT",
    "NUTZLAST_HASH_FALSCH",
    "EMPFAENGER_FREMD",
    "FASSUNG_UNVERTRAEGLICH",
    "UNBEKANNTES_FELD",
    "PFLICHTFELD_FEHLT",
    "BELEG_UNLESBAR",
    "NUTZLASTART_UNBEKANNT",
    # Bekanntes Feld, unbrauchbarer Wert (ab 1.6): ein erzeugt_am, das kein
    # Zeitpunkt ist; ein Betrag, der keine Zahl ist; ein typcode ausserhalb des
    # Wertevorrats. Weder UNBEKANNTES_FELD (das Feld ist bekannt) noch
    # PFLICHTFELD_FEHLT (es ist da).
    "WERT_UNBRAUCHBAR",
    "KETTE_SPRINGT",
    "KETTE_BEGINNT_NEU",
    "ERZEUGT_AM_RUECKWAERTS",
    "BELEG_ID_WIDERSPRUCH",
    "SUMME_STIMMT_NICHT",
    "STUECKZAHLPROBE",
    "PARTNER_ID_UNBEKANNT",
})

_FASSUNG = re.compile(r"^([0-9]+)\.([0-9]+)$")

EIGENER_MAJOR = int(PROTOKOLL_VERSION.split(".")[0])


def hauptteil(fassung) -> Optional[int]:
    """Die Hauptfassung, oder None, wenn das keine Fassungsangabe ist."""
    if not isinstance(fassung, str):
        return None
    treffer = _FASSUNG.match(fassung.strip())
    return int(treffer.group(1)) if treffer else None


def fassung_annehmbar(fassung) -> bool:
    """Gleicher major heisst annehmen, auch bei hoeherem minor.

    Der hoehere minor ist der Fall, der am ehesten falsch gebaut wird: Ein
    Empfaenger, der bei jedem unbekannten minor abbricht, macht aus jeder
    Erweiterung einen major und aus dem Gleichschritt eine Blockade. Umgekehrt
    ist eine minor-Erweiterung nur fuer den EMPFAENGER abwaertsvertraeglich,
    nicht fuer den Sender: ein neues Feld an einen alten Empfaenger ist dort
    UNBEKANNTES_FELD, und zwar ganz, nicht teilweise.
    """
    major = hauptteil(fassung)
    if major is None:
        return False
    return major == EIGENER_MAJOR and major < ABGELEHNT_AB_MAJOR


# Das Feldverzeichnis fuer § 11 (UNBEKANNTES_FELD und PFLICHTFELD_FEHLT). Bis zur
# Fassung 1.1 stand es nur als Beispiel-JSON im Papier; jede Anwendung schrieb es ab,
# und "unbekannt" war in zwei Umsetzungen etwas leicht Verschiedenes. Was hier steht,
# wird gegen das Protokoll gemessen (tests/vektoren/), nicht abgeschrieben.
#
# Gefuehrt sind nur die beiden Arten, die dieser Empfaenger liest: der Umschlag und
# der `abrechnungsauftrag`. Die `erloesmeldung` geht an tantiemen, nicht hierher; die
# `quittung` schreibt diese Anwendung noch nicht.
#
# Wichtig am Auftrag: er traegt NUR NETTO. `steuer`, `brutto`, `steuersatz` und
# `steuerkategorie` stehen weder unter pflicht noch unter erlaubt und sind deshalb
# UNBEKANNTES_FELD. Nicht weil der Wert falsch waere, sondern weil dann zwei Stellen
# dieselbe Zahl behaupten: die Steuer entsteht hier, aus dem Steuerstatus des Kunden
# hinter der partner_id.
#
# Fehlt ein Pflichtfeld, ist der Befund PFLICHTFELD_FEHLT, nicht UNBEKANNTES_FELD:
# das Feld ist bekannt, es ist nur nicht da.
FELDER = {   'umschlag': {   'pflicht': [   'format_version',
                                   'beleg_id',
                                   'nutzlast_art',
                                   'absender',
                                   'empfaenger',
                                   'erzeugt_am',
                                   'vorgaenger_hash',
                                   'nutzlast_sha256',
                                   'nutzlast',
                                   'signatur'],
                    'erlaubt': [],
                    'unterobjekte': {   'signatur': {   'pflicht': [   'verfahren',
                                                                       'schluessel_id',
                                                                       'wert'],
                                                        'erlaubt': []}}},
    'abrechnungsauftrag': {   'pflicht': [   'abrechnungsquartal',
                                             'projekt',
                                             'bemessung',
                                             'grundlagen',
                                             'gutschriften'],
                              'erlaubt': ['vortraege'],
                              'unterobjekte': {   'projekt': {   'pflicht': [   'id',
                                                                                'name'],
                                                                 'erlaubt': []},
                                                  'bemessung': {   'pflicht': [   'erloes_netto',
                                                                                  'direktkosten_netto',
                                                                                  'deckungsbeitrag_netto'],
                                                                   'erlaubt': []},
                                                  'grundlagen[]': {   'pflicht': [   'belegnummer',
                                                                                     'beleg_sha256',
                                                                                     'leistungsperiode',
                                                                                     'erloes_netto'],
                                                                      'erlaubt': []},
                                                  'gutschriften[]': {   'pflicht': [   'beteiligter',
                                                                                       'typcode',
                                                                                       'leistungszeitraum',
                                                                                       'positionen',
                                                                                       'summe'],
                                                                        'erlaubt': []},
                                                  'gutschriften[].beteiligter': {   'pflicht': [   'partner_id'],
                                                                                    'erlaubt': [   'anzeigename']},
                                                  'gutschriften[].leistungszeitraum': {   'pflicht': [   'von',
                                                                                                         'bis'],
                                                                                          'erlaubt': [   ]},
                                                  'gutschriften[].positionen[]': {   'pflicht': [   'nr',
                                                                                                    'bezeichnung',
                                                                                                    'netto'],
                                                                                     'erlaubt': [   'herleitung']},
                                                  'gutschriften[].positionen[].herleitung': {   'pflicht': [   'basis_netto',
                                                                                                               'satz'],
                                                                                                'erlaubt': [   ]},
                                                  'gutschriften[].summe': {   'pflicht': [   'netto'],
                                                                              'erlaubt': [   ]},
                                                  'vortraege[]': {   'pflicht': [   'beteiligter',
                                                                                    'netto',
                                                                                    'grund'],
                                                                     'erlaubt': []}}}}
