from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.company import Company
from app.services.rechnung.fehler import RechnungFehler
from app.services.rechnung.firma import get_company


def firma_laden(db: Session) -> Company:
    """Firmendaten der Ersteinrichtung; `RechnungFehler` des Dienstes wird zu HTTP."""
    try:
        return get_company(db)
    except RechnungFehler as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
