"""App-weite Abhaengigkeit (#22): der Schalter der Beleg-Integration.

Dieselben Pflichten wie beim Update-Hinweis nebenan, aus denselben Vorfaellen:
sie faengt jede Ausnahme, setzt IMMER einen Wert und macht danach ein
`rollback()`, damit die Route eine benutzbare Sitzung bekommt.

Die sichere Richtung ist AUS. Wer nicht weiss, ob die Integration eingerichtet
ist, zeigt sie nicht: ein Menue, das nach einem Datenbankfehler erscheint, waere
schlimmer als eines, das fehlt.
"""

import logging

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.app_config import AppConfig

logger = logging.getLogger(__name__)


def lade_beleg_integration(request: Request, db: Session = Depends(get_db)) -> None:
    request.state.beleg_integration = False
    try:
        cfg = db.query(AppConfig).filter(AppConfig.id == 1).first()
        request.state.beleg_integration = bool(cfg and cfg.beleg_integration_aktiv)
    except Exception:
        request.state.beleg_integration = False
        try:
            db.rollback()
        except Exception:
            logger.exception("Rollback nach fehlgeschlagenem Schalterblick misslungen")
        logger.exception("Schalter der Beleg-Integration nicht lesbar")
