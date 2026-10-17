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

import hashlib
import json
import re
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
    fassung_annehmbar,
    zeit,
)
from app.services.uebergabe_schluessel import (
    SchluesselNichtGueltig,
    SchluesselUnbekannt,
    schluessel_laden,
)
from app.services.uebergabebeleg import (
    EMPFAENGER_ABGEHAKT,
    UebergabeFehler,
    kanonisch,
    kanonisierungsfehler,
)

# Was dieser Empfaenger liest. Die `erloesmeldung` geht an tantiemen, die
# `quittung` schreibt diese Anwendung noch nicht (Stufe 7).
LESBARE_ARTEN = ("abrechnungsauftrag",)

# Ein Pflichtfeld, das da ist und leer, ist bei diesen beiden nicht da: ein
# Auftrag ohne Gutschrift und eine Gutschrift ohne Position tun nichts.
# `grundlagen` und `vortraege` duerfen leer sein - das sind Aussagen.
_LEER_IST_FEHLEND = ("gutschriften", "positionen")

# 389 ist die Abrechnung ueber eine fremde Leistung (Gutschriftverfahren), 381
# die kaufmaennische Gutschrift. Ein anderer Wert ist kein Beleg, den dieser
# Empfaenger ausstellen koennte.
TYPCODES = ("381", "389")

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
    abrechnungsquartal: Optional[str] = None
    projekt: Optional[str] = None
    zahl_gutschriften: Optional[int] = None
    summe_netto: Optional[Decimal] = None

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
        if f"{kind}[]" in unterobjekte:
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


def _auftrag_pruefen(nutzlast: dict, lage: Empfangslage) -> list:
    """§ 8: die drei Pruefhaken und die Aufloesung des Beteiligten.

    Die Formen des § 4 (Geld, Satz) hat _felder_pruefen schon geprueft; hier
    wird nur noch gerechnet, und _zahl kann an keiner Angabe mehr scheitern.

    Gesammelt wird alles Falsche, nicht bloss das Erste: § 10 verlangt JE
    Grund einen Befund. Der Leser meldete bisher nur den ersten - der
    Absender reparierte die eine Stelle, reichte wieder ein, und erst dann
    kam der zweite Befund.
    """
    funde = _felder_pruefen(nutzlast, FELDER["abrechnungsauftrag"], "$.nutzlast")
    if funde:
        return funde

    # Summe grundlagen <= bemessung.erloes_netto. NIE Gleichheit: `grundlagen`
    # ist ein Auszug, kein Nachweis des Erloeses. Als signierte Erloesmeldung
    # kommt heute nur ein Kanal; die uebrigen liest der Absender aus eigenen
    # Importen. Ein Pruefhaken auf Gleichheit lehnte jeden echten Auftrag ab.
    erloes = _zahl(nutzlast["bemessung"]["erloes_netto"])
    summe_grundlagen = Decimal("0")
    for grundlage in nutzlast["grundlagen"]:
        summe_grundlagen += _zahl(grundlage["erloes_netto"])
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
        if not isinstance(typcode, str) or typcode not in TYPCODES:
            funde.append(Feststellung(
                "WERT_UNBRAUCHBAR", f"{pfad}.typcode",
                erwartet=" oder ".join(TYPCODES), erhalten=str(typcode),
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


def _anzeige(nutzlast: dict) -> dict:
    """Was die Tabelle zeigt. Nur Lesen, keine Wirkung.

    Laeuft auch fuer eine abgelehnte Nutzlast, denn die Zeile muss erscheinen,
    damit der Befund erscheint - deshalb ertraegt sie jede Form, die der
    Leser gerade abgelehnt hat.
    """
    gutschriften = nutzlast.get("gutschriften") if isinstance(
        nutzlast.get("gutschriften"), list
    ) else []
    summe = Decimal("0")
    for gutschrift in gutschriften:
        if not isinstance(gutschrift, dict):
            continue
        summe_feld = gutschrift.get("summe")
        betrag = _zahl(summe_feld.get("netto") if isinstance(summe_feld, dict) else None)
        if betrag is not None:
            summe += betrag
    projekt = nutzlast.get("projekt") or {}
    return {
        "abrechnungsquartal": nutzlast.get("abrechnungsquartal"),
        "projekt": projekt.get("name") if isinstance(projekt, dict) else None,
        "zahl_gutschriften": len(gutschriften),
        "summe_netto": summe,
    }


def beleg_beurteilen(
    roh: bytes,
    lage: Optional[Empfangslage] = None,
    *,
    schluessel_wurzel: Optional[Path] = None,
    eigener_name: str = EMPFAENGER_ABGEHAKT,
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
        import base64

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
                nutzlast=nutzlast, **rest, **_anzeige(nutzlast),
            )
        if schon is not None:
            return abgelehnt(Feststellung("BELEG_ID_WIDERSPRUCH", "$.beleg_id",
                                          erwartet=schon, erhalten=sha), **rest)

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
        return abgelehnt(Feststellung("NUTZLASTART_UNBEKANNT", "$.nutzlast_art",
                                      erwartet=", ".join(lesbare_arten),
                                      erhalten=str(beleg["nutzlast_art"])), **rest)

    funde = _auftrag_pruefen(nutzlast, lage)
    if funde:
        return abgelehnt(*funde, nutzlast=nutzlast, **rest, **_anzeige(nutzlast))

    return Belegurteil(
        beleg_sha256=sha, angenommen=True, nutzlast=nutzlast, **rest, **_anzeige(nutzlast),
    )


def herleitungsbetrag(basis: Decimal, satz: Decimal) -> Decimal:
    """Gemeinsame kaufmaennische Rechenprobe fuer Import und manuelle Anlage."""
    return (basis * satz / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
