"""Welche Kunden einem Beleg zugeordnet werden duerfen (#173).

Eine Stelle fuer Formular, Uebergabe-Wirkung und Eingangslage. Zuordenbar ist ein
Kunde nur, wenn er aktiv und nicht soft-geloescht ist. Deaktiviert und unbekannt
(fehlt oder geloescht) bleiben unterscheidbar: Anwenden und Formular melden das
getrennt, damit der Beleg dem richtigen Kunden zugeordnet wird.
"""
from __future__ import annotations

import uuid
from enum import Enum
from typing import Optional

from sqlalchemy.orm import Session

from app.models.customer import Customer

MELDUNG_DEAKTIVIERT = "Kunde ist deaktiviert"
MELDUNG_NICHT_ZUORDENBAR = "Kunde ist nicht zuordenbar"


class Zuordnung(Enum):
    ZUORDENBAR = "zuordenbar"
    DEAKTIVIERT = "deaktiviert"
    UNBEKANNT = "unbekannt"


def zuordenbare_kunden(db: Session) -> list[Customer]:
    """Kunden, die Formulare und Listen zur Auswahl anbieten."""
    return (
        db.query(Customer)
        .filter(Customer.deleted_at.is_(None), Customer.is_active.is_(True))
        .order_by(Customer.name)
        .all()
    )


def kennung_aufloesen(db: Session, kennung) -> tuple[Zuordnung, Optional[Customer]]:
    """Kennung gegen den Stamm: zuordenbar, deaktiviert oder unbekannt."""
    try:
        kunde_id = uuid.UUID(str(kennung))
    except (ValueError, AttributeError, TypeError):
        return Zuordnung.UNBEKANNT, None
    kunde = db.query(Customer).filter(Customer.id == kunde_id).first()
    if kunde is None or kunde.deleted_at is not None:
        return Zuordnung.UNBEKANNT, None
    if not kunde.is_active:
        return Zuordnung.DEAKTIVIERT, kunde
    return Zuordnung.ZUORDENBAR, kunde


def ist_zuordenbar(kunde: Customer) -> bool:
    """Objektpruefung ohne erneute Abfrage (Validator, geladene Beziehungen).

    Fehlende Attribute (Testattrappen) gelten als zuordenbar: nur gesetztes
    deleted_at bzw. is_active=False sperrt.
    """
    if getattr(kunde, "deleted_at", None) is not None:
        return False
    return bool(getattr(kunde, "is_active", True))


def meldung_fuer(lage: Zuordnung, *, partner_id=None) -> str:
    """Fachtext zur Lage; partner_id nur fuer die Uebergabe-Meldung Unbekannt."""
    if lage is Zuordnung.DEAKTIVIERT:
        return MELDUNG_DEAKTIVIERT
    if partner_id is not None:
        return f"Kein Kunde zu partner_id {partner_id}"
    return MELDUNG_NICHT_ZUORDENBAR
