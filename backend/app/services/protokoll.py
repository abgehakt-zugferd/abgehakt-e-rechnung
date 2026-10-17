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
from datetime import datetime
from typing import Optional

PROTOKOLL_VERSION = "1.7"

AKZEPTIERTE_FASSUNGEN = ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7")

ABGELEHNT_AB_MAJOR = 2

# 1.7 fuehrt zwei neue Arten (rechnungsauftrag und aufstellungsauftrag,
# §§ 8a und 8b). Dass sie hier stehen, heisst nur, dass das PROTOKOLL sie
# kennt - die Frage, was dieser Empfaenger LIEST, ist eine andere, und ihre
# Antwort steht in uebergabe_befund.LESBARE_ARTEN. Deren Bau wartet auf eine
# Freigabe: Ein gueltig signierter Beleg der neuen Arten kommt heute durch
# jede Umschlagprobe und faellt an der Artprobe mit NUTZLASTART_UNBEKANNT.
NUTZLAST_ARTEN = (
    "erloesmeldung",
    "abrechnungsauftrag",
    "rechnungsauftrag",
    "aufstellungsauftrag",
    "quittung",
)

# § 8 (ab 1.6): der geschlossene Wertevorrat von gutschriften[].typcode, und
# zugleich die Zuordnung zu der Belegart, die dieser Empfaenger daraus anlegt.
# 389 ist die Abrechnung ueber eine fremde Leistung (Gutschriftverfahren,
# § 14 Abs. 2 UStG), 381 die kaufmaennische Gutschrift; der Unterschied ist
# eine Entscheidung des Absenders und steht im Klartext im Auftrag.
#
# Der Vorrat steht hier und nicht in der Belegarttabelle (belegart.py): Er
# ist Teil des Uebergabeformats und mit den Vektoren gemessen, waehrend die
# BT-3 der Belegarten auch 380, 384, 386 und 261 kennen - im Auftrag sind
# die verboten, und ein Vorrat in belegart.py haette zwei Bedeutungen. Die
# Werte sind die internen Belegarten aus belegart.py; dort bleibt die Quelle
# der Belegarten, hier die der Zuordnung, denn Vorrat und Zuordnung bewegen
# sich zusammen, wenn das Format einen Code ergaenzt. Der Leser prueft die
# Schluessel (uebergabe_befund), die Wirkung liest die Werte
# (abrechnungsauftrag_wirkung).
TYPCODE_BELEGART = {"381": "credit_note", "389": "self_billing"}

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
    # Ab 1.7 (§§ 8a und 8b), an die beiden neuen Arten gebunden: Zum
    # auftragsschluessel besteht bereits ein nicht storniertes Dokument,
    # Entwurf eingeschlossen; die Anlage eines aufstellungsauftrags fehlt
    # oder weicht in Hash oder Groesse ab. Sie begegnen diesem Empfaenger
    # erst, wenn er die neuen Arten liest.
    "AUFTRAG_SCHON_GERECHNET",
    "ANLAGE_FEHLT",
    "ANLAGE_HASH_FALSCH",
})

_FASSUNG = re.compile(r"^([0-9]+)\.([0-9]+)$")


def hauptteil(fassung) -> Optional[int]:
    """Die Hauptfassung, oder None, wenn das keine Fassungsangabe ist."""
    if not isinstance(fassung, str):
        return None
    treffer = _FASSUNG.match(fassung.strip())
    return int(treffer.group(1)) if treffer else None


def fassung_annehmbar(fassung) -> bool:
    """§ 2: Abgelehnt ist nur der HOEHERE major, nicht interpretiert.

    Der hoehere minor bleibt angenommen - der Fall, der am ehesten falsch
    gebaut wird: Ein Empfaenger, der bei jedem unbekannten minor abbricht,
    macht aus jeder Erweiterung einen major und aus dem Gleichschritt eine
    Blockade. Umgekehrt ist eine minor-Erweiterung nur fuer den EMPFAENGER
    abwaertsvertraeglich, nicht fuer den Sender: ein neues Feld an einen
    alten Empfaenger ist dort UNBEKANNTES_FELD, und zwar ganz, nicht
    teilweise.

    Ein NIEDRIGERER major ist ebenso keiner der Abgelehnten: § 2 nennt als
    einzigen Grund den hoeheren, und `format_version` sagt nur, nach welchen
    Regeln DIESER Beleg gebaut ist. Was einer frueheren Fassung fehlt oder
    von ihr abweicht, fallen das Feldverzeichnis (UNBEKANNTES_FELD,
    PFLICHTFELD_FEHLT) und die Wertproben - nicht die Fassung.
    """
    major = hauptteil(fassung)
    if major is None:
        return False
    return major < ABGELEHNT_AB_MAJOR


# § 2: UTC, sekundengenau, ohne Bruchteile. Die Form ist Teil des Werts: Eine
# andere Schreibweise desselben Augenblicks (".123", "+02:00") parste
# fromisoformat anstandslos, und eine naive Angabe crashte erst im Vergleich
# mit dem Beiblatt des Schluessels (TypeError vor jeder Signaturpruefung).
# Erlaubt ist nur die eine Schreibweise. Sie gilt am Umschlag (erzeugt_am)
# und am Beiblatt eines Schluessels (gueltig_von, gueltig_bis) - eine Form,
# eine Stelle: hier, denn seit #166 pruefen sie der Belegleser und der
# Schluessellader gemeinsam.
ZEITFORM = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")


def zeit(wert) -> Optional[datetime]:
    """Ein Zeitpunkt der § 2-Form, oder None - keine Ausnahme.

    Ein Wert, der nicht der Form ist, ist unbrauchbar, egal ob die
    Schreibweise oder der Zeitpunkt nicht stimmt.
    """
    if not isinstance(wert, str) or not ZEITFORM.match(wert):
        return None
    try:
        return datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        # Formproben wie "2026-13-45T99:99:99Z": die Schreibweise stimmt, der
        # Zeitpunkt tut nicht - beides ist ein unbrauchbarer Wert.
        return None


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

# § 4: die Form je Geld- und Satzfeld, als Verzeichnispfad (der Schluessel aus
# FELDER plus Feldname, so wie der Leser ihn bildet). Geld ist eine
# JSON-Zeichenkette mit Dezimalpunkt und GENAU zwei Nachkommastellen. Der Satz
# ist KEIN Geld und traegt MINDESTENS zwei Nachkommastellen - "33.333333" ist
# ein gueltiger Satz, "33.3" keiner (Klarstellung 2026-10-17). Die Zeitform
# des § 2 steht als eigene Regel ueber diesem Verzeichnis (ZEITFORM), denn
# sie gilt nicht je Feld des Belegs, sondern am Umschlag und am Beiblatt
# eines Schluessels.
FELDFORMEN = {
    'bemessung.erloes_netto': 'geld',
    'bemessung.direktkosten_netto': 'geld',
    'bemessung.deckungsbeitrag_netto': 'geld',
    'grundlagen[].erloes_netto': 'geld',
    'gutschriften[].positionen[].netto': 'geld',
    'gutschriften[].positionen[].herleitung.basis_netto': 'geld',
    'gutschriften[].positionen[].herleitung.satz': 'satz',
    'gutschriften[].summe.netto': 'geld',
    'vortraege[].netto': 'geld',
}
