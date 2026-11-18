"""Gesundheitsroute fuer Healthcheck und Proxy: lebt die Anwendung, antwortet die DB?

Gibt bewusst keine Daten aus: weder Firma noch Beleg noch Fehlertext. Ein Proxy
oder Monitor braucht nur "ja" oder "nein"; ein Fehlertext der Datenbank koennte
Hostnamen oder Zugangsdaten verraten. Die Ursache steht im Log des Betreibers.
Keine Anmeldung (die Anwendung hat keine) und kein Template.

Das Einrichtungstor laesst `/gesundheit` durch (`app.dependencies.einrichtungstor`):
ein Healthcheck darf nicht auf `/setup` umgeleitet werden, und bei gestoerter DB darf
schon das Tor nicht an der Abfrage scheitern, bevor diese Route antwortet.
"""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/gesundheit")
def gesundheit(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Gesundheitspruefung: Datenbank nicht erreichbar")
        return JSONResponse({"status": "db_nicht_erreichbar"}, status_code=503)
    return JSONResponse({"status": "ok"})
