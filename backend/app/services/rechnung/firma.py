from sqlalchemy.orm import Session

from app.models.company import Company
from app.services.rechnung.fehler import RechnungFehler


def get_company(db: Session) -> Company:
    c = db.query(Company).filter(Company.id == 1).first()
    # Die Existenz der Zeile beweist nichts: Migration 001 legt sie IMMER an, auf
    # einer frischen Installation ist sie leer. Ein reiner Existenz-Check hätte
    # eine Rechnung mit leerem Verkäufer erzeugt — im PDF und in der ZUGFeRD-XML,
    # die seit 2025 rechtlich maßgeblich ist.
    if not c or c.setup_completed_at is None:
        raise RechnungFehler(400, "Firmendaten nicht konfiguriert. Bitte zuerst die Ersteinrichtung abschließen.")
    return c
