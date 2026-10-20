from sqlalchemy.orm import Session

from app.models.company import Company
from app.services.rechnung.fehler import RechnungFehler


def eingerichtete_firma(
    db: Session, *, for_update: bool = False
) -> Company | None:
    """Firmenzeile nur, wenn die Ersteinrichtung abgeschlossen ist.

    Migration 001 legt die Zeile (id=1) immer an - leer, mit
    `setup_completed_at IS NULL`. Die blosse Existenz beweist nichts.
    """
    q = db.query(Company).filter(Company.id == 1)
    if for_update:
        q = q.with_for_update()
    c = q.first()
    if c is None or c.setup_completed_at is None:
        return None
    return c


def get_company(db: Session) -> Company:
    c = eingerichtete_firma(db)
    # Ein reiner Existenz-Check haette eine Rechnung mit leerem Verkaeufer
    # erzeugt - im PDF und in der ZUGFeRD-XML, die seit 2025 rechtlich
    # massgeblich ist.
    if c is None:
        raise RechnungFehler(
            400,
            "Firmendaten nicht konfiguriert. Bitte zuerst die Ersteinrichtung abschließen.",
        )
    return c
