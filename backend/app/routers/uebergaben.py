"""Die Belege im Ordner ansehen und einen davon anlegen (abgehakt#22).

Zwei Wege, und der Unterschied zwischen ihnen ist der ganze Punkt:

* GET zeigt, was im Ordner liegt. Das Lesen hat KEINE Wirkung: kein Datensatz,
  kein Zustand, keine Zeile. Der Ordner wird nur gelesen; hier schreibt nie
  jemand hinein (§ 12, Archiv nach § 147 AO).
* POST legt an. Erst dieser Knopf persistiert, und er ist ein Mensch.

Ohne den Schalter (Einstellungen) gibt es beide Wege nicht - nicht bloss keinen
Menuepunkt: eine Seite, die man erreicht, wenn man die Adresse kennt, waere
kein ausgeschaltetes Merkmal.
"""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.branding import register_branding_globals
from app.config import get_settings
from app.darstellung import registriere_darstellungsfilter
from app.database import get_db
from app.models.app_config import AppConfig
from app.services.abrechnungsauftrag_wirkung import (
    BelegSchonVerarbeitet,
    WirkungFehler,
    entwuerfe_anlegen,
)
from app.services.uebergabe_befund import beleg_beurteilen
from app.services.uebergabe_eingang import DatenbankLage

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)

# Die Richtung, aus der Belege kommen. Nur diese eine: was in der Gegenrichtung
# liegt, hat dieser Empfaenger geschrieben.
RICHTUNG = "tantiemen-app-nach-abgehakt"


def _schalter(db: Session) -> None:
    """Ohne Schalter gibt es diese Wege nicht."""
    cfg = db.query(AppConfig).filter(AppConfig.id == 1).first()
    if not (cfg and cfg.beleg_integration_aktiv):
        raise HTTPException(status_code=404)


def _schluesselwurzel() -> Optional[Path]:
    pfad = get_settings().schluessel_pfad
    return Path(pfad) if pfad else None


def _belegordner() -> Optional[Path]:
    wurzel = get_settings().uebergaben_ordner
    if not wurzel:
        return None
    ordner = Path(wurzel) / RICHTUNG
    return ordner if ordner.is_dir() else None


def _datei(ordner: Path, dateiname: str) -> Path:
    """Genau eine Datei aus diesem Ordner - oder gar keine.

    Der Name kommt aus der Adresszeile. Ein Pfad, der aus dem Ordner
    hinausfuehrt, ist keine Datei dieses Ordners, sondern ein Versuch.
    """
    if dateiname != Path(dateiname).name or dateiname.startswith("."):
        raise HTTPException(status_code=404)
    datei = (ordner / dateiname).resolve()
    if datei.parent != ordner.resolve() or not datei.is_file():
        raise HTTPException(status_code=404)
    return datei


def _geld(wert) -> str:
    return f"{wert:.2f}".replace(".", ",") if wert is not None else ""


def _zeile(datei: Path, db: Session) -> dict:
    """Ein Beleg, ein Befund. Der Befund entsteht hier und nicht in der Ansicht."""
    urteil = beleg_beurteilen(
        datei.read_bytes(), DatenbankLage(db), schluessel_wurzel=_schluesselwurzel(),
    )
    return {
        "dateiname": datei.name,
        "urteil": urteil,
        "erzeugt_am": urteil.erzeugt_am.strftime("%d.%m.%Y %H:%M") if urteil.erzeugt_am else "",
        "summe_netto": _geld(urteil.summe_netto),
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def belegliste(request: Request, db: Session = Depends(get_db), hinweis: str = "",
               fehler: str = ""):
    _schalter(db)
    ordner = _belegordner()
    zeilen = []
    if ordner is not None:
        zeilen = [_zeile(datei, db) for datei in sorted(ordner.glob("*.json"))]

    return templates.TemplateResponse("uebergaben/index.html", {
        "request": request,
        "ordner": str(ordner) if ordner else "",
        "zeilen": zeilen,
        "hinweis": hinweis,
        "fehler": fehler,
    })


@router.post("/{dateiname}/rechnung-anlegen")
def rechnung_anlegen(dateiname: str, db: Session = Depends(get_db)):
    _schalter(db)
    ordner = _belegordner()
    if ordner is None:
        raise HTTPException(status_code=404)
    datei = _datei(ordner, dateiname)

    # Noch einmal beurteilen, nicht der Ansicht glauben: zwischen dem Anzeigen
    # und dem Knopfdruck kann der Ordner ein anderer sein.
    urteil = beleg_beurteilen(
        datei.read_bytes(), DatenbankLage(db), schluessel_wurzel=_schluesselwurzel(),
    )
    if not urteil.angenommen:
        return RedirectResponse(
            url=f"/uebergaben?fehler={urteil.befund or 'ABGELEHNT'}", status_code=303,
        )

    try:
        entwuerfe = entwuerfe_anlegen(db, urteil, dateiname=datei.name)
        db.commit()
    except BelegSchonVerarbeitet:
        db.rollback()
        return RedirectResponse(url="/uebergaben?hinweis=bereits", status_code=303)
    except WirkungFehler as fehler:
        # Alles oder nichts: was halb entstanden waere, ist damit weg.
        db.rollback()
        return RedirectResponse(url=f"/uebergaben?fehler={fehler}", status_code=303)

    return RedirectResponse(url=f"/invoices/{entwuerfe[0].id}/vorschau", status_code=303)
