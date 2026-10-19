from fastapi import APIRouter

from app.routers.invoices.vorlagen import templates
from app.routers.invoices import (
    ansicht,
    finalisieren,
    formular,
    formular_lesen,
    liste,
    storno_entwurf,
    versand,
)

templates.env.globals["ungueltige_einheiten"] = formular_lesen.ungueltige_einheiten

router = APIRouter()
# Die Reihenfolge ist Verhalten: `/neu` muss vor `/{invoice_id}` stehen.
router.include_router(liste.router)
router.include_router(formular.router)
router.include_router(ansicht.router)
router.include_router(finalisieren.router)
router.include_router(versand.router)
# PDF und Status gehoeren fachlich zum Finalisieren, stehen im Bestand aber
# nach dem Versand — eigener Router, damit die Routenliste gleich bleibt.
router.include_router(finalisieren.status_router)
router.include_router(storno_entwurf.router)

__all__ = ["router", "templates"]
