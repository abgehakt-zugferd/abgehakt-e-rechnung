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
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Optional, Sequence

from cryptography.exceptions import InvalidSignature

from app.services.protokoll import FELDER, NUTZLAST_ARTEN, fassung_annehmbar
from app.services.uebergabe_schluessel import (
    SchluesselNichtGueltig,
    SchluesselUnbekannt,
    schluessel_laden,
)
from app.services.uebergabebeleg import (
    EMPFAENGER_ABGEHAKT,
    kanonisch,
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
    sind 265.77, mit gerundetem Satz 265.73.
    """
    try:
        return Decimal(str(wert))
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def _zeit(wert) -> Optional[datetime]:
    if not isinstance(wert, str):
        return None
    try:
        return datetime.fromisoformat(wert.replace("Z", "+00:00"))
    except ValueError:
        return None


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
        if isinstance(wert, list) and f"{kind}[]" in unterobjekte:
            for nummer, eintrag in enumerate(wert):
                _pruefe_objekt(
                    eintrag, unterobjekte[f"{kind}[]"], unterobjekte,
                    f"{kind}[]", f"{pfad}.{name}[{nummer}]", funde,
                )
        elif isinstance(wert, dict) and kind in unterobjekte:
            _pruefe_objekt(
                wert, unterobjekte[kind], unterobjekte, kind, f"{pfad}.{name}", funde,
            )


def _felder_pruefen(objekt, verzeichnis, pfad) -> list:
    funde: list = []
    _pruefe_objekt(objekt, verzeichnis, verzeichnis.get("unterobjekte", {}), "", pfad, funde)
    return funde


def _auftrag_pruefen(nutzlast: dict, lage: Empfangslage) -> list:
    """§ 8: die drei Pruefhaken und die Aufloesung des Beteiligten."""
    funde = _felder_pruefen(nutzlast, FELDER["abrechnungsauftrag"], "$.nutzlast")
    if funde:
        return funde

    # Summe grundlagen <= bemessung.erloes_netto. NIE Gleichheit: `grundlagen`
    # ist ein Auszug, kein Nachweis des Erloeses. Als signierte Erloesmeldung
    # kommt heute nur ein Kanal; die uebrigen liest der Absender aus eigenen
    # Importen. Ein Pruefhaken auf Gleichheit lehnte jeden echten Auftrag ab.
    erloes = _zahl(nutzlast["bemessung"]["erloes_netto"])
    summe_grundlagen = Decimal("0")
    for nummer, grundlage in enumerate(nutzlast["grundlagen"]):
        betrag = _zahl(grundlage["erloes_netto"])
        if betrag is None:
            return [Feststellung("WERT_UNBRAUCHBAR",
                                 f"$.nutzlast.grundlagen[{nummer}].erloes_netto",
                                 erwartet="Betrag", erhalten=str(grundlage["erloes_netto"]))]
        summe_grundlagen += betrag
    if erloes is None:
        return [Feststellung("WERT_UNBRAUCHBAR", "$.nutzlast.bemessung.erloes_netto",
                             erwartet="Betrag",
                             erhalten=str(nutzlast["bemessung"]["erloes_netto"]))]
    if summe_grundlagen > erloes:
        return [Feststellung(
            "SUMME_STIMMT_NICHT", "$.nutzlast.grundlagen",
            erwartet=f"hoechstens {erloes}", erhalten=str(summe_grundlagen),
        )]

    for nummer, gutschrift in enumerate(nutzlast["gutschriften"]):
        pfad = f"$.nutzlast.gutschriften[{nummer}]"
        typcode = str(gutschrift["typcode"])
        if typcode not in TYPCODES:
            return [Feststellung("WERT_UNBRAUCHBAR", f"{pfad}.typcode",
                                 erwartet=" oder ".join(TYPCODES), erhalten=typcode)]

        summe = Decimal("0")
        for lfd, position in enumerate(gutschrift["positionen"]):
            netto = _zahl(position["netto"])
            if netto is None:
                return [Feststellung("WERT_UNBRAUCHBAR", f"{pfad}.positionen[{lfd}].netto",
                                     erwartet="Betrag", erhalten=str(position["netto"]))]
            summe += netto
            herleitung = position.get("herleitung")
            if herleitung is None:
                # Ohne Herleitung ungeprueft uebernehmen: der Schluessel dahinter
                # ist Innenverhaeltnis und geht diesen Empfaenger nichts an.
                continue
            basis = _zahl(herleitung["basis_netto"])
            satz = _zahl(herleitung["satz"])
            if basis is None or satz is None:
                return [Feststellung("WERT_UNBRAUCHBAR", f"{pfad}.positionen[{lfd}].herleitung",
                                     erwartet="basis_netto und satz als Zahlen")]
            # Kaufmaennisch runden. Pythons Standard waere ROUND_HALF_EVEN und
            # machte aus 174.325 eine 174.32 - der gueltige Auftrag flaege raus.
            erwartet = (basis * satz / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
            if erwartet != netto:
                return [Feststellung(
                    "SUMME_STIMMT_NICHT", f"{pfad}.positionen[{lfd}].netto",
                    erwartet=str(erwartet), erhalten=str(netto),
                )]

        genannt = _zahl(gutschrift["summe"]["netto"])
        if genannt is None:
            return [Feststellung("WERT_UNBRAUCHBAR", f"{pfad}.summe.netto",
                                 erwartet="Betrag", erhalten=str(gutschrift["summe"]["netto"]))]
        if genannt != summe:
            return [Feststellung(
                "SUMME_STIMMT_NICHT", f"{pfad}.summe.netto",
                erwartet=str(summe), erhalten=str(gutschrift["summe"]["netto"]),
            )]

        partner_id = gutschrift["beteiligter"]["partner_id"]
        if not lage.partner_bekannt(str(partner_id)):
            # Ein Kunde entsteht nur von Hand. Und der Auftrag wirkt gar nicht:
            # drei von vier angelegten Gutschriften sind ein Zustand, den von
            # aussen niemand erkennt.
            return [Feststellung("PARTNER_ID_UNBEKANNT", f"{pfad}.beteiligter.partner_id",
                                 erhalten=str(partner_id))]

    return []


def _anzeige(nutzlast: dict) -> dict:
    """Was die Tabelle zeigt. Nur Lesen, keine Wirkung."""
    gutschriften = nutzlast.get("gutschriften") or []
    summe = Decimal("0")
    for gutschrift in gutschriften:
        betrag = _zahl((gutschrift.get("summe") or {}).get("netto"))
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
        beleg = json.loads(roh.decode("utf-8"))
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

    erzeugt_am = _zeit(beleg["erzeugt_am"])
    if erzeugt_am is None:
        # Bekanntes Feld, unbrauchbarer Wert (ab Fassung 1.6). Vorher stand hier
        # BELEG_UNLESBAR, und das war gedehnt: die Datei ist ja lesbar.
        return abgelehnt(Feststellung("WERT_UNBRAUCHBAR", "$.erzeugt_am",
                                      erwartet="RFC 3339, UTC",
                                      erhalten=str(beleg["erzeugt_am"])), **rest)
    rest["erzeugt_am"] = erzeugt_am

    nutzlast = beleg["nutzlast"]
    if hashlib.sha256(kanonisch(nutzlast)).hexdigest() != beleg["nutzlast_sha256"]:
        return abgelehnt(Feststellung(
            "NUTZLAST_HASH_FALSCH", "$.nutzlast_sha256",
            erwartet=hashlib.sha256(kanonisch(nutzlast)).hexdigest(),
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
        import base64

        schluessel.verify(base64.b64decode(signatur["wert"]), kanonisch(ohne_signatur))
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
