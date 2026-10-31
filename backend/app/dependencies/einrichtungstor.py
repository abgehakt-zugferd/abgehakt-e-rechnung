"""App-weites Einrichtungstor (#218).

Ohne abgeschlossene Ersteinrichtung leiten belegerzeugende Seiten auf `/setup`
um. Eine Abhaengigkeit statt Middleware: sie nutzt `get_db` und greift damit
dieselben Test-Overrides wie die uebrigen App-Abhaengigkeiten. `HTTPException`
mit 303 wuerde der HTML-Fehlerhandler in `main` zu einer Fehlerseite machen —
deshalb eine eigene Ausnahme, die nur hier als 303 beantwortet wird.

Ausnahmen (ohne Einrichtung erreichbar): Setup, Einstellungen (dort wird die
Einrichtung seit #205 ebenfalls abgeschlossen), Archiv, GoBD-Export, Updates,
statische Dateien und `/`. Der Compose-Healthcheck trifft `/dashboard`
(docker-compose.yml); dort bleibt die 303-Umleitung, und `curl -f` wertet 3xx
nicht als Fehler.

Kunden: mitgeschuetzt. Stammdaten tragen keine Verkaeuferangaben, stehen aber
nicht auf der Ausnahmeliste des Auftrags; das Tor soll zur Einrichtung fuehren.
"""
# Absichtlich ohne `from __future__ import annotations`: Die Mutationspruefung ersetzt
# Funktionen, und FastAPI loest `Request` dann nicht mehr aus Zeichenketten-Annotationen auf.
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.services.ersteinrichtung import ist_eingerichtet

_SETUP_ZIEL = "/setup"

# Praefixe ohne trailing slash: `/settings` und `/settings/firma` sind beide frei.
_AUSNAHMEN = (
    "/setup",
    "/settings",
    "/archiv",
    "/export",
    "/updates",
    "/static",
)


class EinrichtungOffen(Exception):
    """Ersteinrichtung fehlt — Antwort ist 303 auf /setup, keine Fehlerseite."""


def pfad_ausgenommen(pfad: str) -> bool:
    if pfad == "/" or pfad == "":
        return True
    return any(pfad == p or pfad.startswith(p + "/") for p in _AUSNAHMEN)


def erfordere_einrichtung(
    request: Request, db: Session = Depends(get_db),
) -> None:
    if pfad_ausgenommen(request.url.path):
        return
    firma = db.query(Company).filter(Company.id == 1).first()
    if not ist_eingerichtet(firma):
        raise EinrichtungOffen()


async def _umleitung_auf_setup(
    request: Request, exc: EinrichtungOffen,
) -> RedirectResponse:
    return RedirectResponse(_SETUP_ZIEL, status_code=303)


def anbinden_einrichtungstor(app: FastAPI) -> None:
    """Exception-Handler registrieren. Die Abhaengigkeit steht in app.dependencies."""
    app.add_exception_handler(EinrichtungOffen, _umleitung_auf_setup)
