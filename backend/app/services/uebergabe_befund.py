"""Ein Uebergabebeleg, ein Befund (abgehakt#22).

Das Lesen eines Belegs hat KEINE Wirkung: kein Datensatz, kein Zustand, keine
Zeile, und in den Belegordner wird nie geschrieben (§ 12: der Ordner ist Archiv
nach § 147 AO, und was dort liegt, hat ein Absender hingelegt).

Der Befund entsteht deshalb hier und nur hier, als Ergebnisobjekt, nicht in der
Tabellendarstellung. Er ist spaeter der Inhalt der Quittung (§ 10) und traegt
schon heute, was sie braucht: `beleg_sha256` als Pflicht (er ist immer
ermittelbar, auch ueber eine kaputte Datei) und `beleg_id`, wenn es sie gibt.
Ob die Quittung beim Lesen oder beim Knopfdruck geschrieben wird, ist damit
noch offen, und beides bleibt ohne Umbau moeglich.

Die Reihenfolge der Pruefungen geht von der Datei nach innen: Bytes, Umschlag,
Fassung, Art, Hash, Schluessel und Signatur, Kennung, Kette, Adressat, dann erst
die Nutzlast. Der Befund nennt den ersten Grund, an dem es scheitert; wer den
Adressaten zuerst pruefte, bekaeme fuer einen kaputten fremden Beleg die
harmlosere Auskunft.

Was dieser Empfaenger ueber frueher weiss, wird ihm gereicht (`Empfangslage`)
und nicht hier gesucht: der Leser kennt keine Datenbank und keinen Ordner.
"""

from __future__ import annotations

import base64
import calendar
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Optional, Sequence

from cryptography.exceptions import InvalidSignature

from app.services.protokoll import (
    FELDER,
    FELDFORMEN,
    NUTZLAST_ARTEN,
    TYPCODE_BELEGART,
    fassung_annehmbar,
    zeit,
)
from app.services.uebergabe_schluessel import (
    SchluesselNichtGueltig,
    SchluesselUnbekannt,
    schluessel_laden,
)
from app.services.uebergabebeleg import (
    ABSENDER_TANTIEMEN,
    EMPFAENGER_ABGEHAKT,
    UebergabeFehler,
    kanonisch,
    kanonisierungsfehler,
)

# Was dieser Empfaenger liest. Die `erloesmeldung` geht an tantiemen, die
# `quittung` schreibt diese Anwendung noch nicht (Stufe 7). Der
# `rechnungsauftrag` (§ 8a) ist mit seinem Auftragsschluessel vollstaendig
# gebaut (_rechnungsauftrag_pruefen); was aus ihm WIRD, entscheidet sich in
# einem spaeteren Bauschritt. Der `aufstellungsauftrag` (§ 8b) ist gebaut als
# LESER und nur als Leser (_aufstellungsauftrag_pruefen): kein Entwurf, kein
# Modell - die Anlagenprobe haelt jeden Beleg gegen die Dateien.
LESBARE_ARTEN = ("abrechnungsauftrag", "rechnungsauftrag", "aufstellungsauftrag")

# Ein Pflichtfeld, das da ist und leer, ist bei diesen beiden nicht da: ein
# Auftrag ohne Gutschrift und eine Gutschrift ohne Position tun nichts.
# `grundlagen` und `vortraege` duerfen leer sein - das sind Aussagen. Die
# `anlagen` des § 8b zaehlen NICHT hierher: Eine leere Liste ist dort keine
# Leerstelle, sondern eine falsche Besetzung (WERT_UNBRAUCHBAR), denn der
# Auftrag verlangt GENAU ZWEI.
_LEER_IST_FEHLEND = ("gutschriften", "positionen")

_CENT = Decimal("0.01")


@dataclass(frozen=True)
class Feststellung:
    """Ein Grund. `pfad` nennt das Feld, `$` das ganze Dokument."""

    code: str
    pfad: str
    erwartet: Optional[str] = None
    erhalten: Optional[str] = None


@dataclass(frozen=True)
class Belegurteil:
    beleg_sha256: str
    beleg_id: Optional[str] = None
    angenommen: bool = False
    bereits_verarbeitet: bool = False
    feststellungen: tuple = ()
    absender: Optional[str] = None
    nutzlast_art: Optional[str] = None
    erzeugt_am: Optional[datetime] = None
    vorgaenger_hash: Optional[str] = None
    nutzlast: Optional[dict] = None
    gegenstand: Optional[str] = None
    zeitraum: Optional[str] = None
    summe: Optional[str] = None

    @property
    def befund(self) -> str:
        """Der erste Grund, oder leer. Fuer die Tabelle."""
        return self.feststellungen[0].code if self.feststellungen else ""


class Empfangslage:
    """Was dieser Empfaenger schon gesehen hat.

    Voreinstellung ist die leere Lage: nichts angenommen, keine Kennung bekannt,
    kein Partner im Stamm. Wer nichts weiss, nimmt nichts an - das ist die
    sichere Richtung. Die Fassung mit Datenbank steht in `uebergabe_eingang.py`.
    """

    def zuletzt_angenommen(self, absender: str) -> Optional[tuple]:
        """(beleg_sha256, erzeugt_am) des zuletzt angenommenen Belegs, oder None."""
        return None

    def sha_zu_beleg_id(self, beleg_id: str) -> Optional[str]:
        """Der Hash, unter dem diese Kennung ANGENOMMEN wurde, oder None.

        Nur angenommene: ein abgelehnter Beleg wird nicht gemerkt und darf erneut
        vorgelegt werden. Wer 'verarbeitet' weiter fasst, friert die erste
        Ablehnung ein und macht einen behebbaren Fehler unbehebbar.
        """
        return None

    def partner_bekannt(self, partner_id: str) -> bool:
        return False

    def dokument_zu_auftragsschluessel(self, schluessel: str) -> Optional[str]:
        """Die Rechnungsnummer oder 'Entwurf' des Belegs, der zu diesem
        Auftragsschluessel bereits besteht - oder None.

        § 8a: Der Auftragsschluessel schuetzt vor der zweiten Rechnung zum
        selben Auftrag. Er zaehlt nur Belege, die weder storniert noch
        verworfen sind: Ein stornierter hat nicht gerechnet, und ein
        verworfener Entwurf ist keiner. `beleg_id` schuetzt davor, dass
        DERSELBE Beleg zweimal wirkt - ein neu eingelesener Bericht ist ein
        neuer Beleg, und nur der Schluessel erkennt ihn wieder.
        """
        return None

    def anlagen_bytes(self, sha256: str) -> Optional[bytes]:
        """Die Bytes der Anlage, die unter diesem Hash abgelegt ist - oder
        None, wenn dort keine liegt.

        § 8b: Die Anlagen liegen unter anlagen/<sha256>.xlsx im Uebergabeordner
        der Richtung, VOR dem Beleg geschrieben; der Name ist der Hash. Der
        Ordner gehoert zur Empfangslage und nicht zum Leser, denn der Leser
        kennt keinen Ordner (siehe oben). Die leere Lage kennt keine Anlage,
        und das ist die ehrliche Antwort: Jeder aufstellungsauftrag bekaeme
        ANLAGE_FEHLT. Die Fassung mit Ordner steht in uebergabe_eingang.py,
        sobald der Empfang der Art gebaut wird.
        """
        return None


def _zahl(wert) -> Optional[Decimal]:
    """Betrag oder Satz als Decimal, OHNE zu runden.

    Gerundet wird erst das Ergebnis der Herleitung. Wer den Satz vorher auf zwei
    Stellen zwingt, macht aus 33.333333 % eine 33.33 % und lehnt damit einen
    gueltigen Auftrag ab: gemessen am gueltigen Vektor, 797.30 x 33.333333 %
    sind 265.77, mit gerundetem Satz 265.74.
    """
    try:
        zahl = Decimal(str(wert))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None
    # NaN und Infinity parst Decimal anstandslos, aber der Gleichheitsvergleich
    # mit ihnen ist still False und der Ordnungsvergleich wirft: Ein Betrag
    # "NaN" wurde so zum falschen Befund oder zur Ausnahme. Ein Wert, der mit
    # nichts vergleichbar ist, ist keine Zahl.
    if not zahl.is_finite():
        return None
    return zahl


# § 4, je Form EINE Pruefung und an EINER Stelle angewandt (protokoll.FELDFORMEN
# nennt die Felder). Geld ist eine JSON-Zeichenkette mit Dezimalpunkt und GENAU
# zwei Nachkommastellen - Decimal haette "174.3300", " 174.33" und "1.7433E2"
# still geschluckt, und die Wirkung rundete dann heimlich. Das optionale
# fuehrende Minus bleibt: kein Feld des Auftrags hat dem Leser bisher ein
# Vorzeichen verboten, und die Formprobe aendert am Vorzeichen nichts.
_GELDFORM = re.compile(r"^-?[0-9]+\.[0-9]{2}$")

# Der Satz ist vom Geld getrennt (Klarstellung 2026-10-17): MINDESTENS zwei
# Nachkommastellen, denn ein Satz, der vorher gerundet wird, lehnt den
# gueltigen Auftrag ab (siehe _zahl).
_SATZFORM = re.compile(r"^-?[0-9]+\.[0-9]{2,}$")


def _hat_geldform(wert) -> bool:
    return isinstance(wert, str) and _GELDFORM.match(wert) is not None


def _hat_satzform(wert) -> bool:
    return isinstance(wert, str) and _SATZFORM.match(wert) is not None


# § 8a, Teil 1b: die Formen der grundlagen[]. beleg_sha256 ist der Hash des
# Abrechnungsberichts, klein wie hashlib.hexdigest() ihn bildet - Grossbuchstaben
# sind eine andere Form, kein anderer Wert. leistungsperiode ist ein Monat
# JJJJ-MM, kein Quartal und kein Zeitraum.
_SHA256_FORM = re.compile(r"^[0-9a-f]{64}$")
_MONAT_FORM = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

# § 8a, Teil 1c: die Form des auftragsschluessels - kleine Buchstaben,
# Ziffern, Doppelpunkt und Bindestrich, 1 bis 128 Zeichen. Grossbuchstaben
# und Leerzeichen sind eine andere Form: Der Schluessel wird gezeichnet und
# verglichen, nicht gelesen, und ein anderer Zeichenvorrat machte den
# Vergleich zweier Umsetzungen vom Zufall der Gross- und Kleinschreibung
# abhaengig. Die Form steht hier und nicht in FELDFORMEN, denn dort stehen
# die Geld- und Satzformen des § 4, die JEDE Art betreffen.
_AUFTRAGSSCHLUESSEL_FORM = re.compile(r"^[a-z0-9:-]{1,128}$")


# § 8b: die Formen, die nur der aufstellungsauftrag liest. Die waehrung ist
# ISO 4217 als Form, aber ohne Wertevorrat - ein Vorrat stuende im
# oeffentlichen Code dieses Empfaengers. Der kurs ist weder Geld (genau zwei
# Nachkommastellen) noch Satz (mindestens zwei): Er steht drauf, wie ihn die
# Plattform nennt. Die zahlungsnummer ist eine Kennung aus Ziffern, keine
# Zahl - die xlsx speichert sie als Gleitkommazahl, und
# '100000000000001.0' ist ein anderer Wert.
_WAEHRUNG_FORM = re.compile(r"^[A-Z]{3}$")
_KURS_FORM = re.compile(r"^[0-9]+\.[0-9]+$")
_ZAHLUNGSNUMMER_FORM = re.compile(r"^[0-9]+$")

# § 8b: der geschlossene Bestand der Anlagen - GENAU zwei, je eine quelle,
# hinter jedem anderen Namen steht ein anderer Bericht. groesse ist eine
# Schutzgrenze fuer den Leser, keine Aussage ueber einen Versandweg.
_ANLAGEN_QUELLEN = ("abrechnungsbericht", "zahlungsbericht")
_ANLAGE_MEDIENTYP = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_ANLAGE_GROESSE_HOECHST = 20_000_000


# § 8a, Teil 1b: Gleichheit von gruppe und bezeichnung ist Zeichengleichheit
# nach Unicode-NFC - zerlegtes und zusammengesetztes "ue" sind derselbe Text.
# Keine Nachsicht bei Gross- und Kleinschreibung, und der Wortlaut selbst wird
# nie geprueft: gruppe ist freier Anzeigetext.
def _nfc(wert):
    return unicodedata.normalize("NFC", wert) if isinstance(wert, str) else wert


# Σ grundlagen[feld], die eine Schleife fuer beide Arten: § 8 zaehlt erloes_netto
# gegen bemessung (hoechstens, NIE gleich), § 8a zaehlt netto gegen summe (gleich).
def _grundlagen_summe(nutzlast: dict, feld: str) -> Decimal:
    summe = Decimal("0")
    for grundlage in nutzlast["grundlagen"]:
        summe += _zahl(grundlage[feld])
    return summe


# § 2, die gemeinsame Formprobe fuer Beleg und Schluesselbeiblatt, steht in
# protokoll.py (ZEITFORM, zeit): Sie gilt seit #166 an zwei Stellen, und zwei
# Stellen bedeuten eine Quelle, keine Kopie.


def _datum(wert) -> Optional[date]:
    """Dieselbe Parse-Regel, mit der die Wirkung den Zeitraum liest.

    Nicht aus abrechnungsauftrag_wirkung importierbar, denn die Wirkung
    importiert diesen Leser; die gemeinsame Quelle ist date.fromisoformat
    selbst und keine zweite Regel.
    """
    if not isinstance(wert, str):
        return None
    try:
        return date.fromisoformat(wert)
    except ValueError:
        return None


class _DoppelterName(ValueError):
    """Ein JSON-Objekt mit zwei gleichen Namen.

    json.loads laesst dabei still den letzten gewinnen; der Befund soll schon
    beim Parsen entstehen, damit das Umschreiben des Objekts, das daraus
    folgt, gar nicht erst passiert.
    """

    def __init__(self, name):
        super().__init__(name)
        self.name = name


def _objekt_aus_paaren(paare):
    """object_pairs_hook: sammelt Namen, statt den letzten gewinnen zu lassen."""
    objekt = {}
    for name, wert in paare:
        if name in objekt:
            raise _DoppelterName(name)
        objekt[name] = wert
    return objekt


def _pruefe_objekt(objekt, spec, unterobjekte, pfad_verzeichnis, pfad, funde) -> None:
    """Ein Objekt gegen das Feldverzeichnis. Kein Zaehlen, kein Raten."""
    if not isinstance(objekt, dict):
        funde.append(Feststellung("PFLICHTFELD_FEHLT", pfad, erhalten=type(objekt).__name__))
        return

    bekannt = set(spec["pflicht"]) | set(spec["erlaubt"])
    for name in spec["pflicht"]:
        if name not in objekt:
            funde.append(Feststellung("PFLICHTFELD_FEHLT", f"{pfad}.{name}"))
        elif name in _LEER_IST_FEHLEND and objekt[name] == []:
            funde.append(Feststellung("PFLICHTFELD_FEHLT", f"{pfad}.{name}", erhalten="leer"))

    for name, wert in objekt.items():
        if name not in bekannt:
            funde.append(Feststellung("UNBEKANNTES_FELD", f"{pfad}.{name}"))
            continue
        kind = f"{pfad_verzeichnis}.{name}" if pfad_verzeichnis else name
        # null am OPTIONALEN Unterobjekt heisst "nicht vorhanden", nicht
        # "unbrauchbar" - die Wirkung liest es genau so (position.get(
        # "herleitung") or {}). Ein PFLICHT-Unterobjekt ertraegt null nicht: Es
        # ist da und unbrauchbar. Jeder andere falsche Typ bleibt, was er
        # seit #164 ist.
        fehlt = wert is None and name not in spec["pflicht"]
        if f"{kind}[]" in unterobjekte:
            if fehlt:
                continue
            # Formprobe vor der Annahme: Ein Objekt oder eine Zeichenkette
            # statt der Liste wurde frueher stillschweigend uebernommen und
            # war erst in der Wirkung ein TypeError. Das Feld ist bekannt
            # und da, nur seine Form ist unbrauchbar.
            if not isinstance(wert, list):
                funde.append(Feststellung(
                    "WERT_UNBRAUCHBAR", f"{pfad}.{name}",
                    erwartet="Liste", erhalten=type(wert).__name__,
                ))
                continue
            for nummer, eintrag in enumerate(wert):
                _pruefe_objekt(
                    eintrag, unterobjekte[f"{kind}[]"], unterobjekte,
                    f"{kind}[]", f"{pfad}.{name}[{nummer}]", funde,
                )
        elif kind in unterobjekte:
            if fehlt:
                continue
            if not isinstance(wert, dict):
                funde.append(Feststellung(
                    "WERT_UNBRAUCHBAR", f"{pfad}.{name}",
                    erwartet="Objekt", erhalten=type(wert).__name__,
                ))
                continue
            _pruefe_objekt(
                wert, unterobjekte[kind], unterobjekte, kind, f"{pfad}.{name}", funde,
            )
        else:
            # § 4, einmal zentral: die Formprobe fuer jedes Geld- und Satzfeld
            # des Verzeichnisses (protokoll.FELDFORMEN). Sie laeuft hier und
            # nicht je Verbraucher, damit auch Felder die Form tragen, die
            # dieser Empfaenger nie in eine Rechnung rechnet.
            form = FELDFORMEN.get(kind)
            if form == "geld" and not _hat_geldform(wert):
                funde.append(Feststellung(
                    "WERT_UNBRAUCHBAR", f"{pfad}.{name}",
                    erwartet="Zeichenkette mit genau zwei Nachkommastellen",
                    erhalten=str(wert),
                ))
            elif form == "satz" and not _hat_satzform(wert):
                funde.append(Feststellung(
                    "WERT_UNBRAUCHBAR", f"{pfad}.{name}",
                    erwartet="Zeichenkette mit mindestens zwei Nachkommastellen",
                    erhalten=str(wert),
                ))


def _felder_pruefen(objekt, verzeichnis, pfad) -> list:
    funde: list = []
    _pruefe_objekt(objekt, verzeichnis, verzeichnis.get("unterobjekte", {}), "", pfad, funde)
    return funde


def _auftragsschluessel_pruefen(nutzlast: dict, lage: Empfangslage) -> list:
    """§§ 8a und 8b, gemeinsam: die Form des auftragsschluessels und der
    zweite Haken.

    Erst mit einer Form, die der Empfaenger zeichnen kann, lohnt die Frage
    an die Lage, ob zu diesem Schluessel bereits ein Beleg besteht: Nach
    einem Wert ausserhalb der Form wird nicht gesucht, denn der Absender
    meinte einen anderen.
    """
    funde: list = []
    schluessel = nutzlast["auftragsschluessel"]
    if not isinstance(schluessel, str) \
            or not _AUFTRAGSSCHLUESSEL_FORM.match(schluessel):
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.auftragsschluessel",
            erwartet="1 bis 128 Zeichen aus a-z, 0-9, : und -",
            erhalten=str(schluessel),
        ))
    else:
        schon = lage.dokument_zu_auftragsschluessel(schluessel)
        if schon is not None:
            # Kein Fehler des Absenders, sondern die Abbildung des Bestands:
            # Der Auftrag wurde bereits gerechnet, und im erhalten steht die
            # Rechnungsnummer oder 'Entwurf' des Belegs, der daraus entstand.
            funde.append(Feststellung(
                "AUFTRAG_SCHON_GERECHNET", "$.nutzlast.auftragsschluessel",
                erhalten=schon,
            ))
    return funde


def _kunde_pruefen(nutzlast: dict, lage: Empfangslage) -> list:
    """§§ 8a und 8b, gemeinsam: der Kunde hinter partner_id muss im Stamm
    stehen. Ohne ihn gibt es keine Steuerkategorie und keinen Vermerk, und
    die Steuer wird nicht geraten; beim aufstellungsauftrag gibt es ohne ihn
    niemanden, dem die Aufstellung zugeordnet waere."""
    partner_id = nutzlast["kunde"]["partner_id"]
    if not lage.partner_bekannt(str(partner_id)):
        return [Feststellung(
            "PARTNER_ID_UNBEKANNT", "$.nutzlast.kunde.partner_id",
            erhalten=str(partner_id),
        )]
    return []


def _kalendermonat_pruefen(zeitraum: dict) -> list:
    """§§ 8a und 8b, gemeinsam: genau ein Kalendermonat - von der Erste, bis
    der Letzte desselben Monats. Wer sammelt, verliert die Zuordnung zur
    Zahlung. Gelesen wird mit derselben Regel wie beim abrechnungsauftrag
    (_datum), damit kein gueltiger Auftrag abgelehnt wird."""
    funde: list = []
    von = _datum(zeitraum["von"])
    bis = _datum(zeitraum["bis"])
    if von is None:
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.leistungszeitraum.von",
            erwartet="Datum", erhalten=str(zeitraum["von"]),
        ))
    if bis is None:
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.leistungszeitraum.bis",
            erwartet="Datum", erhalten=str(zeitraum["bis"]),
        ))
    if von is not None and bis is not None:
        letzter = date(von.year, von.month, calendar.monthrange(von.year, von.month)[1])
        if von.day != 1 or (bis.year, bis.month) != (von.year, von.month) or bis != letzter:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", "$.nutzlast.leistungszeitraum",
                erwartet="ein Kalendermonat",
                erhalten=f"von {zeitraum['von']}, bis {zeitraum['bis']}",
            ))
    return funde


def _auftrag_pruefen(nutzlast: dict, lage: Empfangslage, art: str) -> list:
    """§§ 8, 8a und 8b: der Feldbestand aus dem Verzeichnis je Art, dann
    ihre Proben.

    Die Formen des § 4 (Geld, Satz) hat _felder_pruefen schon geprueft; hier
    wird nur noch gerechnet, und _zahl kann an keiner Angabe mehr scheitern.

    Gesammelt wird alles Falsche, nicht bloss das Erste: § 10 verlangt JE
    Grund einen Befund. Der Leser meldete bisher nur den ersten - der
    Absender reparierte die eine Stelle, reichte wieder ein, und erst dann
    kam der zweite Befund.
    """
    funde = _felder_pruefen(nutzlast, FELDER[art], "$.nutzlast")
    if funde:
        return funde
    if art == "rechnungsauftrag":
        return _rechnungsauftrag_pruefen(nutzlast, lage)
    if art == "aufstellungsauftrag":
        return _aufstellungsauftrag_pruefen(nutzlast, lage)
    return _abrechnungsauftrag_pruefen(nutzlast, lage)


def _rechnungsauftrag_pruefen(nutzlast: dict, lage: Empfangslage) -> list:
    """§ 8a (Fassung 1.7): Grundregeln (Teil 1a), die Gruppen, Bezeichnungen
    und Grundlagen (Teil 1b) und den Auftragsschluessel samt Kunde (Teil 1c).
    Wie beim abrechnungsauftrag gilt: Alles Falsche wird gesammelt.
    """
    funde: list = []

    # Teil 1c: Auftragsschluessel und Kunde - seit § 8b gemeinsam mit dem
    # aufstellungsauftrag, eine Quelle, keine Kopie.
    funde += _auftragsschluessel_pruefen(nutzlast, lage)
    funde += _kunde_pruefen(nutzlast, lage)

    # Geschlossene Vorraete. 380 ist die Ausgangsrechnung; 389 ist die
    # Gutschrift aus § 8, ein anderer Beleg, kein Typcode mehr. EUR, bis die
    # Kursfrage beantwortet ist: GBP als Euro zu lesen waere schlimmer als
    # die Ablehnung.
    if nutzlast["typcode"] != "380":
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.typcode",
            erwartet="380", erhalten=str(nutzlast["typcode"]),
        ))
    if nutzlast["waehrung"] != "EUR":
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.waehrung",
            erwartet="EUR", erhalten=str(nutzlast["waehrung"]),
        ))

    # Teil 1a: Genau ein Kalendermonat, seit § 8b gemeinsam.
    funde += _kalendermonat_pruefen(nutzlast["leistungszeitraum"])

    summe = Decimal("0")
    for nummer, position in enumerate(nutzlast["positionen"]):
        netto = _zahl(position["netto"])
        summe += netto
        # Positionen duerfen negativ sein, nie 0.00: Der Sender laesst sie
        # weg, und eine Position ueber nichts ist keine Auskunft.
        if netto == 0:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"$.nutzlast.positionen[{nummer}].netto",
                erwartet="nicht 0.00", erhalten=str(position["netto"]),
            ))

    genannt = _zahl(nutzlast["summe"]["netto"])
    if genannt != summe:
        funde.append(Feststellung(
            "SUMME_STIMMT_NICHT", "$.nutzlast.summe.netto",
            erwartet=str(summe), erhalten=str(nutzlast["summe"]["netto"]),
        ))
    # Eine Rechnung ueber null oder weniger ist keine 380; der Sender haette
    # keinen Auftrag erzeugen duerfen. Die Summen koennen aufgehen - deshalb
    # SUMME_STIMMT_NICHT am Feld und nicht WERT_UNBRAUCHBAR: Die Probe gilt
    # der Rechnung als ganzer, nicht dem einzelnen Wert.
    if genannt <= 0:
        funde.append(Feststellung(
            "SUMME_STIMMT_NICHT", "$.nutzlast.summe.netto",
            erwartet="groesser als 0.00", erhalten=str(nutzlast["summe"]["netto"]),
        ))

    # Teil 1b haengt unten an: Gruppen, Bezeichnungen, Grundlagen.
    funde += _rechnungsauftrag_gruppen_pruefen(nutzlast)
    funde += _rechnungsauftrag_bezeichnungen_pruefen(nutzlast)
    funde += _rechnungsauftrag_grundlagen_pruefen(nutzlast)
    return funde


def _rechnungsauftrag_gruppen_pruefen(nutzlast: dict) -> list:
    """§ 8a, Teil 1b: gruppe an allen Positionen oder an keiner, jede Gruppe
    in einem Zug, ihre Positionen in nr lueckenlos.

    Gleiche Gruppe heisst zeichengleich nach Unicode-NFC (_nfc); der Wortlaut
    selbst wird nie geprueft. Ohne jede gruppe ist die Rechnung ungegliedert
    und gueltig - der Zwang gilt erst, wenn EINE Position eine gruppe traegt.
    """
    funde: list = []
    positionen = nutzlast["positionen"]

    # Alle oder keine: Eine gruppe an EINER Position gliedert die ganze
    # Rechnung. Eine einzelne Position ohne gliedert nichts und verdoppelt
    # die Lesart; null zaehlt wie die § 2-Klarstellung als nicht vorhanden.
    if any(position.get("gruppe") is not None for position in positionen):
        for nummer, position in enumerate(positionen):
            if position.get("gruppe") is None:
                funde.append(Feststellung(
                    "WERT_UNBRAUCHBAR", f"$.nutzlast.positionen[{nummer}].gruppe",
                    erwartet="Gruppe an jeder Position", erhalten="keine Gruppe",
                ))

    # Zusammenhaengend: Kehrt eine Gruppe nach einer anderen zurueck, bricht
    # die ERSTE zurueckkehrende Position den Zusammenhang - und genau sie
    # wird gemeldet (gemessen am Vektor gruppe_unterbrochen). Kehrt danach
    # noch eine zweite zurueck, so kehrt sie nur zurueck, WEIL die erste es
    # tat: Das ist ein Grund, nicht zwei. Die Reihenfolge der Gruppen ist
    # die ihrer ersten Position; nr zaehlt je Gruppe ohne Luecke weiter
    # (nur ganze Zahlen: nr traegt keine Formprobe, eine andere Form prueft
    # hier niemand).
    offen = None
    geschlossen: list = []
    vorige_nr = None
    gemeldet = False
    for nummer, position in enumerate(positionen):
        gruppe = position.get("gruppe")
        if gruppe is None:
            continue
        schluessel = _nfc(gruppe)
        if schluessel != offen:
            if schluessel in geschlossen and not gemeldet:
                funde.append(Feststellung(
                    "WERT_UNBRAUCHBAR", f"$.nutzlast.positionen[{nummer}].gruppe",
                    erwartet="zusammenhaengende Gruppe", erhalten=str(gruppe),
                ))
                gemeldet = True
            if offen is not None and offen not in geschlossen:
                geschlossen.append(offen)
            offen = schluessel
            vorige_nr = None
        nr = position.get("nr")
        if isinstance(nr, int) and isinstance(vorige_nr, int) and nr != vorige_nr + 1:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"$.nutzlast.positionen[{nummer}].nr",
                erwartet=str(vorige_nr + 1), erhalten=str(nr),
            ))
        vorige_nr = nr
    return funde


def _rechnungsauftrag_bezeichnungen_pruefen(nutzlast: dict) -> list:
    """§ 8a, Teil 1b: keine zwei Positionen mit derselben bezeichnung.

    Gleich ist zeichengleich nach Unicode-NFC (_nfc). Der Befund trifft die
    zweite Stelle: Die erste blieb unbeanstandet, und der Absender sieht so,
    welche zu aendern ist.
    """
    funde: list = []
    gesehen: list = []
    for nummer, position in enumerate(nutzlast["positionen"]):
        bezeichnung = _nfc(position["bezeichnung"])
        if bezeichnung in gesehen:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"$.nutzlast.positionen[{nummer}].bezeichnung",
                erwartet="nur einmal je Beleg", erhalten=str(position["bezeichnung"]),
            ))
        else:
            gesehen.append(bezeichnung)
    return funde


def _rechnungsauftrag_grundlagen_pruefen(nutzlast: dict) -> list:
    """§ 8a, Teil 1b: die Grundlagen sind die Herleitung, kein Auszug.

    quelle ist heute nur der abrechnungsbericht - hinter jedem anderen Namen
    steht ein anderer Bericht, und Grossschreibung ist ein anderer Name.
    beleg_sha256 (_SHA256_FORM) und leistungsperiode (_MONAT_FORM) tragen ihre
    Form hier und nur hier, denn nur der rechnungsauftrag liest sie. Σ netto
    == summe.netto, exakt: Anders als § 8 (dort hoechstens, NIE gleich) ist
    die Herleitung kein Auszug.
    """
    funde: list = []
    for nummer, grundlage in enumerate(nutzlast["grundlagen"]):
        pfad = f"$.nutzlast.grundlagen[{nummer}]"
        if grundlage["quelle"] != "abrechnungsbericht":
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.quelle",
                erwartet="abrechnungsbericht", erhalten=str(grundlage["quelle"]),
            ))
        if not isinstance(grundlage["beleg_sha256"], str) \
                or not _SHA256_FORM.match(grundlage["beleg_sha256"]):
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.beleg_sha256",
                erwartet="64 Kleinbuchstaben-Hex",
                erhalten=str(grundlage["beleg_sha256"]),
            ))
        if not isinstance(grundlage["leistungsperiode"], str) \
                or not _MONAT_FORM.match(grundlage["leistungsperiode"]):
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.leistungsperiode",
                erwartet="JJJJ-MM", erhalten=str(grundlage["leistungsperiode"]),
            ))

    summe = _grundlagen_summe(nutzlast, "netto")
    genannt = _zahl(nutzlast["summe"]["netto"])
    if summe != genannt:
        funde.append(Feststellung(
            "SUMME_STIMMT_NICHT", "$.nutzlast.grundlagen",
            erwartet=str(genannt), erhalten=str(summe),
        ))
    return funde


def _aufstellungsauftrag_pruefen(nutzlast: dict, lage: Empfangslage) -> list:
    """§ 8b (Fassung 1.7): die Abrechnungsaufstellung bei Drittlandzahlung.

    Keine Rechnung (§ 14 UStG): kein typcode, keine Steuerfelder - die
    Quellensteuer ist ein Einbehalt des Auszahlers, keine Steuer, die hier
    entstuende. Auftragsschluessel, Kunde und Kalendermonat teilt die Art mit
    dem rechnungsauftrag (§ 8a), deshalb die gemeinsamen Proben. Die
    Reihenfolge: Felder (schon geprueft), dann Werte und Summen, DANN die
    Dateien - nur ein in sich brauchbarer Beleg wird gegen die Dateien
    gehalten, sonst hiesse der Befund ANLAGE_FEHLT, obwohl der Absender
    zuerst die Nutzlast reparieren muss.
    """
    funde: list = []

    # §§ 8a und 8b gemeinsam: der Schluessel und der Kunde hinter ihm.
    funde += _auftragsschluessel_pruefen(nutzlast, lage)
    funde += _kunde_pruefen(nutzlast, lage)

    # Die waehrung als Form (ISO 4217), ohne Wertevorrat: Ein Vorrat stuende
    # im oeffentlichen Code dieses Empfaengers. Eine gebrochene Form traegt
    # die genau-dann-Regel der umrechnung nicht - nach ihr wird nicht
    # entschieden, der Befund steht schon.
    waehrung = nutzlast["waehrung"]
    waehrung_formig = isinstance(waehrung, str) and _WAEHRUNG_FORM.match(waehrung)
    if not waehrung_formig:
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.waehrung",
            erwartet="drei Grossbuchstaben", erhalten=str(waehrung),
        ))
    elif waehrung == "EUR":
        # Bei EUR gibt es nichts umzurechnen; das Feld ist dann unbekannt -
        # nicht nach dem Verzeichnis (dort steht es als erlaubt), sondern
        # nach der genau-dann-Regel hier.
        if "umrechnung" in nutzlast:
            funde.append(Feststellung("UNBEKANNTES_FELD", "$.nutzlast.umrechnung"))
    elif "umrechnung" not in nutzlast:
        funde.append(Feststellung("PFLICHTFELD_FEHLT", "$.nutzlast.umrechnung"))

    # Genau ein Kalendermonat, wie § 8a.
    funde += _kalendermonat_pruefen(nutzlast["leistungszeitraum"])

    # netto ist der eine abgeleitete Wert: Der Sender rundet brutto und
    # quellensteuer kaufmaennisch und bildet netto daraus. Exakt, ohne
    # Toleranz - ein Cent daneben ist keiner.
    betraege = nutzlast["betraege"]
    brutto = _zahl(betraege["brutto"])
    quellensteuer = _zahl(betraege["quellensteuer"])
    netto = _zahl(betraege["netto"])
    if brutto - quellensteuer != netto:
        funde.append(Feststellung(
            "SUMME_STIMMT_NICHT", "$.nutzlast.betraege.netto",
            erwartet=str(brutto - quellensteuer), erhalten=str(betraege["netto"]),
        ))
    # Ein Einbehalt des Auszahlers ist nie negativ; die Betraege gehen hier
    # gerade auf, und deshalb faellt es sonst nicht auf.
    if quellensteuer < 0:
        funde.append(Feststellung(
            "SUMME_STIMMT_NICHT", "$.nutzlast.betraege.quellensteuer",
            erwartet="nie negativ", erhalten=str(betraege["quellensteuer"]),
        ))
    # Unbrauchbar ist der Wert, nicht die Summe: Der Sender bildet netto aus
    # brutto und quellensteuer und haette ueber nichts keinen Auftrag
    # erzeugen duerfen.
    if netto <= 0:
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.betraege.netto",
            erwartet="groesser als 0.00", erhalten=str(betraege["netto"]),
        ))

    umrechnung = nutzlast.get("umrechnung")
    if isinstance(umrechnung, dict):
        # Der kurs steht drauf, wie ihn die Plattform nennt: Dezimalpunkt,
        # so viele Nachkommastellen wie gedruckt - weder Geld- noch Satzform.
        kurs = umrechnung["kurs"]
        if not isinstance(kurs, str) or not _KURS_FORM.match(kurs):
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", "$.nutzlast.umrechnung.kurs",
                erwartet="Dezimalbruch als Zeichenkette", erhalten=str(kurs),
            ))
        if umrechnung["waehrung"] != "EUR":
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", "$.nutzlast.umrechnung.waehrung",
                erwartet="EUR", erhalten=str(umrechnung["waehrung"]),
            ))
        # netto x kurs == zahlbetrag wird NICHT geprueft: Die Plattform
        # rechnet die Umrechnung, eine Abweichung waere eine gedruckte
        # Tatsache.

    # Die Zahlung: eine Kennung aus Ziffern und ein Datum. Wer die Nummer
    # als Zahl parst, verliert die fuehrenden Nullen und verwechselt zwei
    # Zahlungen; die xlsx speichert sie als Gleitkommazahl, und
    # '100000000000001.0' ist ein anderer Wert.
    nummer = nutzlast["zahlung"]["zahlungsnummer"]
    if not isinstance(nummer, str) or not _ZAHLUNGSNUMMER_FORM.match(nummer):
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.zahlung.zahlungsnummer",
            erwartet="Ziffernfolge als Zeichenkette", erhalten=str(nummer),
        ))
    if _datum(nutzlast["zahlung"]["datum"]) is None:
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.zahlung.datum",
            erwartet="Datum", erhalten=str(nutzlast["zahlung"]["datum"]),
        ))

    # GENAU zwei Anlagen, je eine quelle: Die Aufstellung zaehlt beiden
    # Berichten, und ein anderer Bestand waere eine andere Aufstellung. Eine
    # andere Anzahl ist WERT_UNBRAUCHBAR, nicht PFLICHTFELD_FEHLT - auch die
    # leere Liste, denn anlagen zaehlt nicht zu _LEER_IST_FEHLEND.
    anlagen = nutzlast["anlagen"]
    quellen = [anlage["quelle"] for anlage in anlagen]
    if len(anlagen) != 2:
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.anlagen",
            erwartet="zwei Anlagen (abrechnungsbericht und zahlungsbericht)",
            erhalten=str(len(anlagen)),
        ))
    elif sorted(quellen) != sorted(_ANLAGEN_QUELLEN):
        funde.append(Feststellung(
            "WERT_UNBRAUCHBAR", "$.nutzlast.anlagen",
            erwartet="je eine Anlage aus abrechnungsbericht und zahlungsbericht",
            erhalten=", ".join(quellen),
        ))
    for nummer, anlage in enumerate(anlagen):
        pfad = f"$.nutzlast.anlagen[{nummer}]"
        if not isinstance(anlage["sha256"], str) \
                or not _SHA256_FORM.match(anlage["sha256"]):
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.sha256",
                erwartet="64 Kleinbuchstaben-Hex",
                erhalten=str(anlage["sha256"]),
            ))
        # True ist in Python eine Ganzzahl, aber keine Groesse; die Grenzen
        # schuetzen den Leser, nicht den Versandweg.
        groesse = anlage["groesse"]
        if not isinstance(groesse, int) or isinstance(groesse, bool) \
                or not 1 <= groesse <= _ANLAGE_GROESSE_HOECHST:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.groesse",
                erwartet=f"Ganzzahl von 1 bis {_ANLAGE_GROESSE_HOECHST}",
                erhalten=str(groesse),
            ))
        if anlage["medientyp"] != _ANLAGE_MEDIENTYP:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.medientyp",
                erwartet=_ANLAGE_MEDIENTYP, erhalten=str(anlage["medientyp"]),
            ))
        # dateiname bleibt ungeprueft: freier Text, und der Name nennt
        # vielleicht eine Plattform oder eine Firma - abgehakt ist
        # oeffentlich, solche Namen reisen als freie Daten.

    if funde:
        return funde

    # Erst jetzt die Dateien (§ 8b): Die Anlage liegt unter
    # anlagen/<sha256>.xlsx im Uebergabeordner der Richtung, VOR dem Beleg
    # geschrieben - es gibt keinen Zwischenzustand, in dem der Beleg ohne
    # Anlage sinnvoll laege. Der Leser oeffnet sie nicht: Hash und Groesse
    # der Bytes sagen, ob die Datei die ist, die der Eintrag nennt; was IN
    # ihr steht, liest der Mensch.
    for nummer, anlage in enumerate(anlagen):
        pfad = f"$.nutzlast.anlagen[{nummer}]"
        bytes_ = lage.anlagen_bytes(anlage["sha256"])
        if bytes_ is None:
            funde.append(Feststellung(
                "ANLAGE_FEHLT", pfad,
                erwartet=f"anlagen/{anlage['sha256']}.xlsx",
            ))
            continue
        gelesen = hashlib.sha256(bytes_).hexdigest()
        if gelesen != anlage["sha256"]:
            funde.append(Feststellung(
                "ANLAGE_HASH_FALSCH", f"{pfad}.sha256",
                erwartet=gelesen, erhalten=str(anlage["sha256"]),
            ))
        elif len(bytes_) != anlage["groesse"]:
            funde.append(Feststellung(
                "ANLAGE_HASH_FALSCH", f"{pfad}.groesse",
                erwartet=str(len(bytes_)), erhalten=str(anlage["groesse"]),
            ))
    return funde


def _abrechnungsauftrag_pruefen(nutzlast: dict, lage: Empfangslage) -> list:
    """§ 8: die drei Pruefhaken und die Aufloesung des Beteiligten."""
    funde: list = []

    # Summe grundlagen <= bemessung.erloes_netto. NIE Gleichheit: `grundlagen`
    # ist ein Auszug, kein Nachweis des Erloeses. Als signierte Erloesmeldung
    # kommt heute nur ein Kanal; die uebrigen liest der Absender aus eigenen
    # Importen. Ein Pruefhaken auf Gleichheit lehnte jeden echten Auftrag ab.
    erloes = _zahl(nutzlast["bemessung"]["erloes_netto"])
    summe_grundlagen = _grundlagen_summe(nutzlast, "erloes_netto")
    if summe_grundlagen > erloes:
        funde.append(Feststellung(
            "SUMME_STIMMT_NICHT", "$.nutzlast.grundlagen",
            erwartet=f"hoechstens {erloes}", erhalten=str(summe_grundlagen),
        ))

    for nummer, gutschrift in enumerate(nutzlast["gutschriften"]):
        pfad = f"$.nutzlast.gutschriften[{nummer}]"
        # § 4: typcode ist eine JSON-Zeichenkette. str() machte aus der Zahl
        # 389 still einen gueltigen Code, und der Absender erfaehrt nie, dass
        # sein Beleg falsch gebaut ist.
        typcode = gutschrift["typcode"]
        if not isinstance(typcode, str) or typcode not in TYPCODE_BELEGART:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.typcode",
                erwartet=" oder ".join(TYPCODE_BELEGART), erhalten=str(typcode),
            ))

        # Wertprobe vor der Annahme: Ein Zeitraum, den die Wirkung spaeter
        # nicht lesen kann, war vorher angenommen und wirkte als ValueError.
        # Gelesen wird mit derselben Regel (date.fromisoformat), nicht mit
        # einer strengeren, damit kein gueltiger Auftrag abgelehnt wird.
        zeitraum = gutschrift["leistungszeitraum"]
        von = _datum(zeitraum["von"])
        bis = _datum(zeitraum["bis"])
        if von is None:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.leistungszeitraum.von",
                erwartet="Datum", erhalten=str(zeitraum["von"]),
            ))
        if bis is None:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.leistungszeitraum.bis",
                erwartet="Datum", erhalten=str(zeitraum["bis"]),
            ))
        if von is not None and bis is not None and von > bis:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.leistungszeitraum",
                erwartet="von vor bis",
                erhalten=f"von {zeitraum['von']}, bis {zeitraum['bis']}",
            ))

        summe = Decimal("0")
        for lfd, position in enumerate(gutschrift["positionen"]):
            netto = _zahl(position["netto"])
            summe += netto
            # § 8a je Position, nicht nur je Summe: Der Validator weist bei 389
            # einen Einzelpreis 0 und einen negativen ab; nahm der Leser solche
            # Positionen an, war der Entwurf gebunden und nie finalisierbar.
            # Leser und Validator nehmen damit dieselbe Menge an.
            if typcode == "389" and netto <= 0:
                funde.append(Feststellung(
                    "WERT_UNBRAUCHBAR", f"{pfad}.positionen[{lfd}].netto",
                    erwartet="groesser als 0.00", erhalten=str(position["netto"]),
                ))
            herleitung = position.get("herleitung")
            if herleitung is None:
                # Ohne Herleitung ungeprueft uebernehmen: der Schluessel dahinter
                # ist Innenverhaeltnis und geht diesen Empfaenger nichts an.
                continue
            basis = _zahl(herleitung["basis_netto"])
            satz = _zahl(herleitung["satz"])
            # Kaufmaennisch runden. Pythons Standard waere ROUND_HALF_EVEN und
            # machte aus 174.325 eine 174.32 - der gueltige Auftrag flaege raus.
            erwartet = herleitungsbetrag(basis, satz)
            if erwartet != netto:
                funde.append(Feststellung(
                    "SUMME_STIMMT_NICHT", f"{pfad}.positionen[{lfd}].netto",
                    erwartet=str(erwartet), erhalten=str(netto),
                ))

        genannt = _zahl(gutschrift["summe"]["netto"])
        # § 8a: Eine Gutschrift des Verfahrens (389) zahlt an den Beteiligten;
        # ueber null oder weniger ist sie keine, und der Sender erzeugt dann
        # keinen Auftrag. WERT_UNBRAUCHBAR am Feld, nicht SUMME_STIMMT_NICHT:
        # Die Summe kann aufgehen (und geht hier auf) - unbrauchbar ist der
        # Wert. Der Probe fehlt der typcode, deshalb steht sie am Feld summe.
        if typcode == "389" and genannt <= 0:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.summe.netto",
                erwartet="groesser als 0.00", erhalten=str(gutschrift["summe"]["netto"]),
            ))
        if genannt != summe:
            funde.append(Feststellung(
                "SUMME_STIMMT_NICHT", f"{pfad}.summe.netto",
                erwartet=str(summe), erhalten=str(gutschrift["summe"]["netto"]),
            ))

        partner_id = gutschrift["beteiligter"]["partner_id"]
        if not lage.partner_bekannt(str(partner_id)):
            # Ein Kunde entsteht nur von Hand. Und der Auftrag wirkt gar nicht:
            # drei von vier angelegten Gutschriften sind ein Zustand, den von
            # aussen niemand erkennt.
            funde.append(Feststellung(
                "PARTNER_ID_UNBEKANNT", f"{pfad}.beteiligter.partner_id",
                erhalten=str(partner_id),
            ))

    return funde


def _anzeige(nutzlast: dict, nutzlast_art: Optional[str] = None) -> dict:
    """Was die Tabelle zeigt. Nur Lesen, keine Wirkung.

    Laeuft auch fuer eine abgelehnte Nutzlast, denn die Zeile muss erscheinen,
    damit der Befund erscheint - deshalb ertraegt sie jede Form, die der
    Leser gerade abgelehnt hat. Eine Quelle: uebergabe_listenzeile.anzeigefelder.
    """
    # Spaeter Import: listenzeile darf befund nicht beim Modulladen ziehen.
    from app.services.uebergabe_listenzeile import anzeigefelder
    return anzeigefelder(nutzlast, nutzlast_art)


def beleg_beurteilen(
    roh: bytes,
    lage: Optional[Empfangslage] = None,
    *,
    schluessel_wurzel: Optional[Path] = None,
    eigener_name: str = EMPFAENGER_ABGEHAKT,
    erwarteter_absender: str = ABSENDER_TANTIEMEN,
    lesbare_arten: Sequence[str] = LESBARE_ARTEN,
) -> Belegurteil:
    """Beurteilt die Bytes eines Belegs. Schreibt nichts, aendert nichts."""
    lage = lage or Empfangslage()
    sha = hashlib.sha256(roh).hexdigest()

    def abgelehnt(*feststellungen, **anzeige) -> Belegurteil:
        return Belegurteil(beleg_sha256=sha, feststellungen=tuple(feststellungen), **anzeige)

    try:
        beleg = json.loads(
            roh.decode("utf-8"), object_pairs_hook=_objekt_aus_paaren,
        )
    except _DoppelterName as fehler:
        # Ein doppelter Name ist eine Datei, die nicht die kanonische Form
        # sein kann (RFC 8785 schreibt jeden Namen einmal). Der Befundcode
        # SIGNATUR_UNGUELTIG ("nicht die signierten Bytes") gilt hier und bei
        # der Kanonprobe unten, bis das Format etwas anderes festlegt.
        return abgelehnt(Feststellung("SIGNATUR_UNGUELTIG", "$", erhalten=fehler.name))
    except (UnicodeDecodeError, json.JSONDecodeError):
        # Die Kennung steht in Bytes, die niemand lesen kann; der Hash ueber die
        # Datei ist trotzdem zu bilden. Der Empfaenger kann immer sagen, WELCHE
        # Bytes er abgelehnt hat.
        return abgelehnt(Feststellung("BELEG_UNLESBAR", "$"))
    if not isinstance(beleg, dict):
        return abgelehnt(Feststellung("BELEG_UNLESBAR", "$", erhalten=type(beleg).__name__))

    kennung = beleg.get("beleg_id") if isinstance(beleg.get("beleg_id"), str) else None
    rest = {"beleg_id": kennung}

    funde = _felder_pruefen(beleg, FELDER["umschlag"], "$")
    if funde:
        return abgelehnt(*funde, **rest)

    rest.update(
        absender=beleg["absender"],
        nutzlast_art=beleg["nutzlast_art"],
        vorgaenger_hash=beleg["vorgaenger_hash"],
    )

    if not fassung_annehmbar(beleg["format_version"]):
        return abgelehnt(Feststellung("FASSUNG_UNVERTRAEGLICH", "$.format_version",
                                      erhalten=str(beleg["format_version"])), **rest)

    if beleg["nutzlast_art"] not in NUTZLAST_ARTEN:
        return abgelehnt(Feststellung("NUTZLASTART_UNBEKANNT", "$.nutzlast_art",
                                      erhalten=str(beleg["nutzlast_art"])), **rest)

    erzeugt_am = zeit(beleg["erzeugt_am"])
    if erzeugt_am is None:
        # Bekanntes Feld, unbrauchbarer Wert (ab Fassung 1.6). Vorher stand hier
        # BELEG_UNLESBAR, und das war gedehnt: die Datei ist ja lesbar. Seit #163
        # gilt die Form des § 2, nicht bloss RFC 3339 irgendeiner Zone.
        return abgelehnt(Feststellung("WERT_UNBRAUCHBAR", "$.erzeugt_am",
                                      erwartet="YYYY-MM-DDTHH:MM:SSZ",
                                      erhalten=str(beleg["erzeugt_am"])), **rest)
    rest["erzeugt_am"] = erzeugt_am

    nutzlast = beleg["nutzlast"]
    try:
        nutzlast_kanonisch = kanonisch(nutzlast)
    except UebergabeFehler:
        # WERT_UNBRAUCHBAR, nicht BELEG_UNLESBAR: Die Datei ist lesbar, das
        # Feld ist bekannt, nur der Wert kanonisiert nicht - RFC 8785 ohne
        # Gleitkommazahlen, dieses Format traegt Betraege als Zeichenketten.
        # BELEG_UNLESBAR waere wieder gedehnt wie beim erzeugt_am vor 1.6.
        pfad, wert = kanonisierungsfehler(nutzlast, "$.nutzlast")
        return abgelehnt(Feststellung(
            "WERT_UNBRAUCHBAR", pfad,
            erwartet="Zeichenkette oder Ganzzahl", erhalten=str(wert),
        ), **rest)
    if hashlib.sha256(nutzlast_kanonisch).hexdigest() != beleg["nutzlast_sha256"]:
        return abgelehnt(Feststellung(
            "NUTZLAST_HASH_FALSCH", "$.nutzlast_sha256",
            erwartet=hashlib.sha256(nutzlast_kanonisch).hexdigest(),
            erhalten=str(beleg["nutzlast_sha256"]),
        ), **rest)

    signatur = beleg["signatur"]
    try:
        schluessel = schluessel_laden(
            beleg["absender"], signatur["schluessel_id"], erzeugt_am, wurzel=schluessel_wurzel,
        )
    except (SchluesselUnbekannt, SchluesselNichtGueltig):
        # Der Schluesselordner IST die Absenderliste (§ 6): von wem hier kein
        # Schluessel liegt, von dem wird nichts angenommen.
        return abgelehnt(Feststellung("SCHLUESSEL_UNBEKANNT", "$.signatur.schluessel_id",
                                      erhalten=str(signatur["schluessel_id"])), **rest)

    ohne_signatur = {name: wert for name, wert in beleg.items() if name != "signatur"}
    try:
        umschlag_kanonisch = kanonisch(ohne_signatur)
    except UebergabeFehler:
        # Dieselbe Probe fuer den Umschlag: Eine Gleitkommazahl ausserhalb der
        # Nutzlast scheiterte hier genauso ohne Stellenangabe.
        pfad, wert = kanonisierungsfehler(ohne_signatur, "$")
        return abgelehnt(Feststellung(
            "WERT_UNBRAUCHBAR", pfad,
            erwartet="Zeichenkette oder Ganzzahl", erhalten=str(wert),
        ), **rest)
    # § 3: Die Datei IST die kanonische Form (RFC 8785). Die Signatur gilt
    # ueber die gelesenen Bytes, und deshalb gilt vor der Pruefung:
    # Bytes == kanonisch(json.loads(Bytes)). Ohne diese Probe nahm der Leser
    # eine eingerueckte Ansicht desselben Belegs an (er pruefte die Signatur
    # ueber das neu kanonisierte Objekt), und beleg_sha256 entstand ueber die
    # abweichende Datei - die Kette reisst beim naechsten Beleg, der diesen
    # Hash als vorgaenger nennt. Befundcode SIGNATUR_UNGUELTIG ("nicht die
    # signierten Bytes"), bis das Format etwas anderes festlegt.
    try:
        ist_kanonisch = kanonisch(beleg) == roh
    except UebergabeFehler:
        # Hier kann nur noch die Signatur selbst unkanonisierbar sein; der
        # Umschlag und die Nutzlast sind oben schon geprueft.
        ist_kanonisch = False
    if not ist_kanonisch:
        return abgelehnt(Feststellung("SIGNATUR_UNGUELTIG", "$"), **rest)

    try:
        schluessel.verify(base64.b64decode(signatur["wert"]), umschlag_kanonisch)
    except (InvalidSignature, ValueError):
        return abgelehnt(Feststellung("SIGNATUR_UNGUELTIG", "$.signatur.wert"), **rest)

    if kennung is not None:
        schon = lage.sha_zu_beleg_id(kennung)
        if schon == sha:
            # Zweimal eingelesen heisst einmal gewirkt: dieselbe Quittung noch
            # einmal, keine Ablehnung.
            return Belegurteil(
                beleg_sha256=sha, angenommen=True, bereits_verarbeitet=True,
                nutzlast=nutzlast, **rest,
                **_anzeige(nutzlast, rest.get("nutzlast_art")),
            )
        if schon is not None:
            return abgelehnt(Feststellung("BELEG_ID_WIDERSPRUCH", "$.beleg_id",
                                          erwartet=schon, erhalten=sha), **rest)

    # Kette: zwei Stufen. "Angenommen" im Befund heisst ANNEHMBAR; gewirkt hat
    # ein Beleg erst, wenn der Knopf ALS RECHNUNG ANLEGEN ihn ueber
    # entwuerfe_anlegen gemerkt hat (uebergabe_eingang.merken, § 5). Die Lage
    # kennt nur gemerkte Belege: Bis der Vorgaenger gewirkt hat, gilt dieser
    # Empfaenger als ohne Vorgeschichte, und ein Folgebeleg, der ihn als
    # vorgaenger_hash nennt, erhaelt KETTE_SPRINGT. Kein Fehler, sondern die
    # Abbildung: die Kette bildet ab, was gewirkt hat, nicht was gelesen wurde.
    zuletzt = lage.zuletzt_angenommen(beleg["absender"])
    vorgaenger = beleg["vorgaenger_hash"]
    if zuletzt is None:
        if vorgaenger is not None:
            return abgelehnt(Feststellung("KETTE_SPRINGT", "$.vorgaenger_hash",
                                          erwartet="null", erhalten=str(vorgaenger)), **rest)
    else:
        letzter_hash, letzte_zeit = zuletzt
        if vorgaenger is None:
            return abgelehnt(Feststellung("KETTE_BEGINNT_NEU", "$.vorgaenger_hash",
                                          erwartet=letzter_hash), **rest)
        if vorgaenger != letzter_hash:
            return abgelehnt(Feststellung("KETTE_SPRINGT", "$.vorgaenger_hash",
                                          erwartet=letzter_hash, erhalten=str(vorgaenger)), **rest)
        if letzte_zeit is not None and erzeugt_am < letzte_zeit:
            # Gleich ist erlaubt: ein Sammellauf traegt denselben Zeitstempel.
            return abgelehnt(Feststellung("ERZEUGT_AM_RUECKWAERTS", "$.erzeugt_am",
                                          erwartet=letzte_zeit.isoformat(),
                                          erhalten=erzeugt_am.isoformat()), **rest)

    if beleg["empfaenger"] != eigener_name:
        return abgelehnt(Feststellung("EMPFAENGER_FREMD", "$.empfaenger",
                                      erwartet=eigener_name,
                                      erhalten=str(beleg["empfaenger"])), **rest)

    if beleg["nutzlast_art"] not in lesbare_arten:
        # Das Wort ist gedehnt, und das bleibt so (der Code ist Bestandteil
        # der Quittung und mit den Vektoren gemessen): Nicht jede Art, die
        # das PROTOKOLL kennt (NUTZLAST_ARTEN), liest dieser Empfaenger
        # (lesbare_arten) - die erloesmeldung geht an tantiemen, die quittung
        # schreibt diese Anwendung noch nicht. Der geschlossene Befundvorrat
        # kennt kein "kannte ich, lese ich aber nicht"; die Codeliste kommt
        # vom Format, nicht von der Lesbarkeit dieses Empfaengers.
        return abgelehnt(Feststellung("NUTZLASTART_UNBEKANNT", "$.nutzlast_art",
                                      erwartet=", ".join(lesbare_arten),
                                      erhalten=str(beleg["nutzlast_art"])), **rest)

    # § 1: Der Abrechnungsauftrag ist die Richtung von EINEM Absender zu diesem
    # Empfaenger. Der Schluesselordner allein genuegt nicht: Ein Schluessel,
    # der fuer einen anderen Absender (eine andere Richtung) liegt, machte
    # seinen Inhaber still zum Absender von Auftraegen. WERT_UNBRAUCHBAR und
    # nicht SCHLUESSEL_UNBEKANNT: Das Feld ist bekannt und der Schluessel kann
    # voellig gueltig sein - unbrauchbar ist der WERT, der ausserhalb des
    # Absenders liegt, dessen Auftraege dieser Leser liest. Einen eigenen
    # Absender-Code fuehrt der geschlossene Vorrat (§ 11) nicht.
    if beleg["absender"] != erwarteter_absender:
        return abgelehnt(Feststellung(
            "WERT_UNBRAUCHBAR", "$.absender",
            erwartet=erwarteter_absender, erhalten=str(beleg["absender"]),
        ), **rest)

    funde = _auftrag_pruefen(nutzlast, lage, beleg["nutzlast_art"])
    if funde:
        return abgelehnt(
            *funde, nutzlast=nutzlast, **rest,
            **_anzeige(nutzlast, beleg["nutzlast_art"]),
        )

    return Belegurteil(
        beleg_sha256=sha, angenommen=True, nutzlast=nutzlast, **rest,
        **_anzeige(nutzlast, beleg["nutzlast_art"]),
    )


def herleitungsbetrag(basis: Decimal, satz: Decimal) -> Decimal:
    """Gemeinsame kaufmaennische Rechenprobe fuer Import und manuelle Anlage."""
    return (basis * satz / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
