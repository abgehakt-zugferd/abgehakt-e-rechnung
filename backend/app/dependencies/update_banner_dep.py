"""
App-weite Abhängigkeit (#120): legt den fertigen Banner auf `request.state`.

Vier Pflichten, alle aus einem Review oder einem Vorfall:
1. Sie fängt JEDE Ausnahme — wirft sie, antworten alle Routen mit 500.
2. Sie setzt IMMER einen Wert. Ein fehlendes request.state-Attribut rendert in
   Jinja stumm als Undefined; der Banner fiele dann lautlos aus.
3. Sie macht danach ein `rollback()` (#150). Das Abfangen allein genügt nicht:
   nach einem Datenbankfehler ist die TRANSAKTION abgebrochen, und weil die
   Route dieselbe Sitzung weiterbenutzt, stirbt jede folgende Abfrage mit
   `InFailedSqlTransaction`. Ohne Rollback ist das Abfangen nur eine
   Verzögerung des Absturzes — und eine, die die Ursache unkenntlich macht.
4. Sie schreibt eine Logzeile. Still gegenüber dem Nutzer (ein Update-Hinweis
   ist nichts, wogegen er handeln könnte), nicht gegenüber dem Betreiber.
"""
import logging
from datetime import datetime, timezone

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.app_config import AppConfig
from app.services.update_banner import compute_banner, compute_mitteilung

logger = logging.getLogger(__name__)


def load_update_banner(request: Request, db: Session = Depends(get_db)) -> None:
    request.state.update_banner = None
    request.state.mitteilung = None
    try:
        cfg = db.query(AppConfig).filter(AppConfig.id == 1).first()
        if cfg is None:
            return
        request.state.update_banner = compute_banner(
            cfg, get_settings().app_version, datetime.now(timezone.utc)
        )
        # Getrennt berechnet: der Pro-Hinweis erscheint auch dann, wenn es
        # gerade gar keinen Update-Banner gibt.
        request.state.mitteilung = compute_mitteilung(cfg)
    except Exception:
        # Ein kaputter Hinweis darf die Anwendung nicht unbenutzbar machen.
        request.state.update_banner = None
        request.state.mitteilung = None
        # Die Sitzung wieder benutzbar machen, BEVOR die Route sie bekommt.
        # Ein zweites Scheitern hier (Verbindung weg) darf die Seite erst recht
        # nicht mitnehmen.
        try:
            db.rollback()
        except Exception:
            logger.exception("Rollback nach fehlgeschlagenem Update-Hinweis misslungen")
        logger.exception("Update-Hinweis konnte nicht geladen werden")
