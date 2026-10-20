"""Das Gedaechtnis des Lesens, an die Datenbank gebunden (abgehakt#22).

`uebergabe_befund.py` kennt keine Datenbank: es bekommt die Lage gereicht. Hier
steht die Fassung, die sie aus dem Bestand beantwortet, und das Merken eines
angenommenen Belegs.

Dazu die eigene Aufbewahrungskopie (§ 12, abgehakt#167): Der Empfaenger bewahrt
den Beleg genauso auf wie der Absender, acht Jahre, unveraendert. Die Kopie
liegt im eigenen Speicher und teilt damit die Aufbewahrung der Rechnungen;
die Anwendung loescht unter storage/ nie etwas. Seit § 8b bewahrt dieselbe
Stelle auch die ANLAGEN eines aufstellungsauftrags auf - beides sind Nachweise
desselben Empfangs, und was fuer den Beleg gilt (pruefen, atomar, idempotent),
gilt fuer die Anlage.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.uebergabe_eingang import UebergabeEingang
from app.services import auftragsschluessel
from app.services.kunde_zuordenbar import Zuordnung, kennung_aufloesen
from app.services.uebergabe_befund import Belegurteil, Empfangslage

# Die Richtung, aus der Belege kommen. Nur diese eine: was in der
# Gegenrichtung liegt, hat dieser Empfaenger geschrieben. Hier und nicht im
# Router wohnt sie, weil ausser dem Router auch die Wirkungen in diesen
# Ordner schreiben (Belegkopie und Anlagen) und beide denselben Namen
# brauchen - zwei Konstanten waeren eine, die auseinanderlaufen kann.
RICHTUNG = "tantiemen-app-nach-abgehakt"


class DatenbankLage(Empfangslage):
    """Was dieser Empfaenger schon gesehen hat, aus dem Bestand beantwortet.

    Seit § 8b kennt sie auch den Anlagenordner des Übergabeordners: Der
    Leser selbst kennt keinen Ordner, die Lage reicht ihm die Bytes.
    """

    def __init__(self, db: Session, anlagen_ordner: Optional[Path] = None):
        self._db = db
        self._anlagen_ordner = anlagen_ordner

    def zuletzt_angenommen(self, absender: str) -> Optional[tuple]:
        zeile = (
            self._db.query(UebergabeEingang)
            .filter(UebergabeEingang.absender == absender)
            # Nach der Reihenfolge der ANNAHME, nicht nach der Erzeugung: die
            # Kette bildet ab, was hier gewirkt hat (§ 5).
            .order_by(UebergabeEingang.angenommen_am.desc(), UebergabeEingang.id.desc())
            .first()
        )
        return (zeile.beleg_sha256, zeile.erzeugt_am) if zeile else None

    def sha_zu_beleg_id(self, beleg_id: str) -> Optional[str]:
        zeile = (
            self._db.query(UebergabeEingang)
            .filter(UebergabeEingang.beleg_id == beleg_id)
            .first()
        )
        return zeile.beleg_sha256 if zeile else None

    def partner_bekannt(self, partner_id: str) -> bool:
        """Die partner_id IST die Kennung des Kunden. Kein Anlegen: ein Kunde
        entsteht nur von Hand, und Zuordnung ueber den Namen ist keine Option.

        Deaktiviert zaehlt hier als bekannt (#173): der Beleg bleibt annehmbar,
        erst das Anwenden scheitert mit klarer Meldung. Unbekannt/geloescht
        bleibt False (PARTNER_ID_UNBEKANNT beim Lesen).
        """
        lage, _kunde = kennung_aufloesen(self._db, partner_id)
        return lage in (Zuordnung.ZUORDENBAR, Zuordnung.DEAKTIVIERT)

    def dokument_zu_auftragsschluessel(self, schluessel: str) -> Optional[str]:
        # Die Frage geht an die eine Stelle fuer die Sperre
        # (services/auftragsschluessel.py): Was dort sperrt, ist der Bestand,
        # den dieser Empfanger zu kennen hat. Bauschritt 4b fragt dort
        # zusaetzlich die Abrechnungsaufstellung ab — das Format spricht von
        # "einem Dokument" (Festlegung 12), beide Tabellen gehoeren in die
        # Antwort.
        return auftragsschluessel.dokument_zu(self._db, schluessel)

    def anlagen_bytes(self, sha256: str) -> Optional[bytes]:
        """§ 8b: Die Anlage liegt als anlagen/<sha256>.xlsx im Uebergabeordner
        der Richtung - derselbe Weg, den der Leser ueber diese Frage geht.
        Ohne Ordner ist None die ehrliche Antwort: Der Leser meldet
        ANLAGE_FEHLT und nimmt den Beleg nicht an.
        """
        if self._anlagen_ordner is None:
            return None
        datei = self._anlagen_ordner / f"{sha256}.xlsx"
        try:
            return datei.read_bytes() if datei.is_file() else None
        except OSError:
            return None


def merken(db: Session, urteil: Belegurteil, *, dateiname: Optional[str] = None) -> UebergabeEingang:
    """Haelt einen angenommenen Beleg fest. Committet nicht.

    Das ist der Uebergang von der ersten Stufe zur zweiten: ANNEHMBAR war der
    Beleg schon mit dem Befund des Lesers, GEWIRKT hat er erst mit dieser
    Zeile, und sie entsteht nur ueber den Knopf ALS RECHNUNG ANLEGEN
    (entwuerfe_anlegen). Erst mit ihr kennt die Kette den Beleg als
    vorgaenger; ein Folgebeleg vor dem Knopfdruck erhaelt KETTE_SPRINGT.
    """
    if not urteil.angenommen:
        raise ValueError(
            "Ein abgelehnter Beleg wird nicht gemerkt: er darf erneut vorgelegt werden."
        )
    if not urteil.beleg_id:
        raise ValueError("Ohne beleg_id gibt es nichts zu merken.")

    vorhanden = (
        db.query(UebergabeEingang)
        .filter(UebergabeEingang.beleg_sha256 == urteil.beleg_sha256)
        .first()
    )
    if vorhanden:
        return vorhanden

    zeile = UebergabeEingang(
        beleg_id=urteil.beleg_id,
        beleg_sha256=urteil.beleg_sha256,
        absender=urteil.absender or "",
        nutzlast_art=urteil.nutzlast_art or "",
        erzeugt_am=urteil.erzeugt_am or datetime.now(timezone.utc),
        dateiname=dateiname,
    )
    db.add(zeile)
    return zeile


class KopieFehler(ValueError):
    """Die Aufbewahrungskopie ist nicht entstanden - beim Beleg wie bei einer
    Anlage des aufstellungsauftrags. Der Beleg wird daraufhin nicht angenommen
    (§ 12): eine Wirkung ohne eigene Kopie waere Aufbewahrung auf Verlaub des
    Absenderordners."""


# Eine Stunde statt sofort: solange liegt die Datei eines Schreibvorgangs, der
# gerade laeuft, und darf nicht weggeraeumt werden (Issue #160).
_VERWAIST_NACH_SEKUNDEN = 3600


def _verwaiste_raeumen(ordner: Path) -> None:
    """Entfernt .kopie-Reste, die ein Absturz zurueckgelassen hat.

    Der finally-Block unten erreicht einen harten Absturz (Prozess weg) nicht;
    die halbe Datei bliebe fuer immer liegen, weil die Anwendung unter storage/
    sonst nichts loescht. Es sind keine Belege und keine Anlagen, sondern
    abgebrochene Schreibvorgaenge: ihr endgueltiger Name waere der Hash-Name
    ({sha}.json beim Beleg, {sha}.xlsx bei der Anlage), so heissen sie nicht.
    Best effort: Scheitert das Raeumen einzelner Dateien, bleiben sie
    liegen, die Annahme des Belegs darf an Muell nicht scheitern.
    """
    schwelle = time.time() - _VERWAIST_NACH_SEKUNDEN
    for rest in ordner.glob(".kopie-*"):
        try:
            if rest.stat().st_mtime < schwelle:
                rest.unlink()
        except OSError:
            continue


def _atomar_schreiben(ordner: Path, ziel: Path, roh: bytes, sha256: str) -> None:
    """Schreibt temporaer im Zielordner, prueft und benennt atomar um.

    Die Temporaerdatei liegt im selben Verzeichnis: os.replace bleibt damit
    auf einem Dateisystem. Nur sie darf weggeraeumt werden; unter storage/
    loescht die Anwendung sonst nichts. Massgeblich ist der Hash der
    GESCHRIEBENEN Datei, nicht der der Bytes im Gedaechtnis - nur er beweist,
    was auf der Platte liegt.
    """
    with tempfile.NamedTemporaryFile(
        dir=ordner, prefix=".kopie-", delete=False,
    ) as hand:
        hand.write(roh)
        zwischenstand = Path(hand.name)
    try:
        if hashlib.sha256(zwischenstand.read_bytes()).hexdigest() != sha256:
            raise KopieFehler(
                "Die geschriebene Aufbewahrungskopie stimmt nicht mit dem "
                "angegebenen SHA-256 ueberein."
            )
        os.replace(zwischenstand, ziel)
    finally:
        zwischenstand.unlink(missing_ok=True)


def kopie_aufbewahren(
    roh: bytes,
    sha256: str,
    richtung: str,
    *,
    endung: str = "json",
    unterordner: Optional[str] = None,
) -> Path:
    """Bewahrt gelesene Bytes unveraendert im eigenen Speicher auf (§ 12: acht
    Jahre, auch beim Empfaenger) und gibt den Zielpfad zurueck.

    Eine Stelle, zwei Gaeste (§ 8b): der Uebergabebeleg liegt direkt im Ordner
    der Richtung (endung json), die Anlagen eines aufstellungsauftrags darunter
    im Unterordner anlagen (endung xlsx) - beides sind Nachweise, und was fuer
    das eine gilt, gilt fuer das andere. Deshalb steht die Logik HIER einmal
    und nicht neben jedem Aufrufer.

    Fail closed: Jedes Scheitern wird als KopieFehler gemeldet, damit der
    Aufrufer den Beleg ablehnen kann. Erst die gepruefte Kopie, dann die
    Datenbankzeilen: scheitert deren Commit, bleibt die Kopie liegen, aber sie
    ist byte-gleich mit den vorgelegten Bytes und schadet niemandem.
    """
    ordner = get_settings().storage_path / "uebergaben" / richtung
    if unterordner is not None:
        ordner = ordner / unterordner
    ziel = ordner / f"{sha256}.{endung}"
    try:
        if ziel.exists():
            # Idempotenz: derselbe Inhalt noch einmal ablegen darf am Bestand
            # nichts aendern - zwei Aufstellungen teilen sich eine Anlage.
            # Anderer Inhalt unter gleichem Namen waere keine Kopie, sondern
            # eine Faelschung der Aufbewahrung.
            if hashlib.sha256(ziel.read_bytes()).hexdigest() == sha256:
                return ziel
            raise KopieFehler(
                f"Unter {ziel} liegt bereits anderer Inhalt fuer diesen Hash."
            )
        ordner.mkdir(parents=True, exist_ok=True)
        # Erst Muell vom letzten Absturz weg, dann die neue Datei: ein
        # stehenbleibender Rest waere bei der naechsten Pruefung nicht von
        # einem frischen zu unterscheiden.
        _verwaiste_raeumen(ordner)
        _atomar_schreiben(ordner, ziel, roh, sha256)
        return ziel
    except OSError as fehler:
        raise KopieFehler(
            f"Die Aufbewahrungskopie liess sich nicht schreiben: {fehler}"
        ) from fehler
