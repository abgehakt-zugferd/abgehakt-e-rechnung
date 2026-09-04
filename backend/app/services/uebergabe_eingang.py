"""Das Gedaechtnis des Lesens, an die Datenbank gebunden (abgehakt#22).

`uebergabe_befund.py` kennt keine Datenbank: es bekommt die Lage gereicht. Hier
steht die Fassung, die sie aus dem Bestand beantwortet, und das Merken eines
angenommenen Belegs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

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
    """Haelt einen angenommenen Beleg fest. Committet nicht."""
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
        erzeugt_am=urteil.erzeugt_am or datetime.now(),
        dateiname=dateiname,
    )
    db.add(zeile)
    return zeile
