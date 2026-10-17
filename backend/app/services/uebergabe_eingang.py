"""Das Gedaechtnis des Lesens, an die Datenbank gebunden (abgehakt#22).

`uebergabe_befund.py` kennt keine Datenbank: es bekommt die Lage gereicht. Hier
steht die Fassung, die sie aus dem Bestand beantwortet, und das Merken eines
angenommenen Belegs.

Dazu die eigene Aufbewahrungskopie (§ 12, abgehakt#167): Der Empfaenger bewahrt
den Beleg genauso auf wie der Absender, acht Jahre, unveraendert. Die Kopie
liegt im eigenen Speicher und teilt damit die Aufbewahrung der Rechnungen;
die Anwendung loescht unter storage/ nie etwas.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.customer import Customer
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.uebergabe_befund import Belegurteil, Empfangslage


class DatenbankLage(Empfangslage):
    """Was dieser Empfaenger schon gesehen hat, aus dem Bestand beantwortet."""

    def __init__(self, db: Session):
        self._db = db

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
        entsteht nur von Hand, und Zuordnung ueber den Namen ist keine Option."""
        try:
            kennung = uuid.UUID(str(partner_id))
        except (ValueError, AttributeError, TypeError):
            return False
        return (
            self._db.query(Customer.id)
            .filter(Customer.id == kennung, Customer.deleted_at.is_(None))
            .first()
            is not None
        )


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
    """Die Aufbewahrungskopie ist nicht entstanden. Der Beleg wird daraufhin
    nicht angenommen (§ 12): eine Wirkung ohne eigene Kopie waere Aufbewahrung
    auf Verlaub des Absenderordners."""


def kopie_aufbewahren(roh: bytes, beleg_sha256: str, richtung: str) -> Path:
    """Bewahrt die gelesenen Bytes des Belegs unveraendert im eigenen Speicher
    auf (§ 12: acht Jahre, auch beim Empfaenger) und gibt den Zielpfad zurueck.

    Fail closed: Jedes Scheitern wird als KopieFehler gemeldet, damit der
    Aufrufer den Beleg ablehnen kann. Erst die gepruefte Kopie, dann die
    Datenbankzeilen: scheitert deren Commit, bleibt die Kopie liegen, aber sie
    ist byte-gleich mit dem Beleg und schadet niemandem.
    """
    ordner = get_settings().storage_path / "uebergaben" / richtung
    ziel = ordner / f"{beleg_sha256}.json"
    try:
        if ziel.exists():
            # Idempotenz: derselbe Beleg noch einmal annehmen darf am Bestand
            # nichts aendern. Anderer Inhalt unter gleichem Namen waere keine
            # Kopie, sondern eine Fälschung der Aufbewahrung.
            if hashlib.sha256(ziel.read_bytes()).hexdigest() == beleg_sha256:
                return ziel
            raise KopieFehler(
                f"Unter {ziel} liegt bereits anderer Inhalt fuer diesen Beleg."
            )
        ordner.mkdir(parents=True, exist_ok=True)
        # Temporaerdatei im selben Verzeichnis: os.replace bleibt damit auf
        # einem Dateisystem und umbenennt atomar. Nur sie darf weggeraeumt
        # werden; unter storage/ loescht die Anwendung sonst nichts.
        with tempfile.NamedTemporaryFile(
            dir=ordner, prefix=".kopie-", delete=False,
        ) as hand:
            hand.write(roh)
            zwischenstand = Path(hand.name)
        try:
            # Massgeblich ist der Hash der GESCHRIEBENEN Datei, nicht der der
            # Bytes im Gedaechtnis: nur er beweist, was auf der Platte liegt.
            if hashlib.sha256(zwischenstand.read_bytes()).hexdigest() != beleg_sha256:
                raise KopieFehler(
                    "Die geschriebene Aufbewahrungskopie stimmt nicht mit dem Beleg ueberein."
                )
            os.replace(zwischenstand, ziel)
        finally:
            zwischenstand.unlink(missing_ok=True)
        return ziel
    except OSError as fehler:
        raise KopieFehler(
            f"Die Aufbewahrungskopie liess sich nicht schreiben: {fehler}"
        ) from fehler
