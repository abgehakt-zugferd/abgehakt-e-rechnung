"""Liste, Detail und Handgriffe der eigenständigen Abrechnungsaufstellung.

Kein XML-Weg und kein E-Rechnungs-Endpoint: Die Aufstellung ist keine Rechnung.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session, joinedload
from fastapi.templating import Jinja2Templates

from app.branding import register_branding_globals
from app.darstellung import registriere_darstellungsfilter
from app.models.aufstellung_send_log import AufstellungSendLog
from app.services.aufstellung_entwurf import wechseln

from app.config import get_settings
from app.database import get_db
from app.models.aufstellung import Aufstellung
from app.services.aufstellung_finalisieren import FinalisierenFehler, finalisieren
from app.services.aufstellung_storno import StornoFehler

router = APIRouter()
settings = get_settings()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)
SEITENGROESSE = 50
STATUS = {"draft": "Entwurf", "issued": "Gestellt", "cancelled": "Storniert", "discarded": "Verworfen"}


@router.get("")
@router.get("/")
def liste(request: Request, db: Session = Depends(get_db), status: str = "", seite: int = 1):
    query = db.query(Aufstellung)
    if status:
        query = query.filter(Aufstellung.status == status)
    gesamt = query.count()
    seiten = max(1, -(-gesamt // SEITENGROESSE))
    seite = min(max(seite, 1), seiten)
    zeilen = (query.options(joinedload(Aufstellung.customer))
              .order_by(Aufstellung.created_at.desc(), Aufstellung.id)
              .offset((seite - 1) * SEITENGROESSE).limit(SEITENGROESSE).all())
    return templates.TemplateResponse("aufstellungen/list.html", {
        "request": request, "aufstellungen": zeilen, "status_filter": status,
        "statusnamen": STATUS, "gesamt": gesamt, "seite": seite, "seiten": seiten,
    })


@router.get("/{aufstellung_id}")
def detail(aufstellung_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    a = db.get(Aufstellung, aufstellung_id)
    if not a:
        raise HTTPException(404)
    stornos = db.query(Aufstellung).filter(Aufstellung.storniert_id == a.id).order_by(Aufstellung.created_at).all()
    logs = db.query(AufstellungSendLog).filter(
        AufstellungSendLog.aufstellung_id == a.id,
    ).order_by(AufstellungSendLog.sent_at.desc()).all()
    return templates.TemplateResponse("aufstellungen/detail.html", {
        "request": request, "a": a, "stornos": stornos, "logs": logs, "statusnamen": STATUS,
    })


def _entwurf_wechsel(aufstellung_id, db, zurueckholen=False):
    a = db.query(Aufstellung).filter(Aufstellung.id == aufstellung_id).with_for_update().first()
    if not a:
        raise HTTPException(404)
    wechseln(db, a, zurueckholen)
    return RedirectResponse(url=f"/aufstellungen/{a.id}", status_code=303)


@router.post("/{aufstellung_id}/verwerfen")
def verwerfen(aufstellung_id: uuid.UUID, db: Session = Depends(get_db)):
    return _entwurf_wechsel(aufstellung_id, db)


@router.post("/{aufstellung_id}/zurueckholen")
def zurueckholen(aufstellung_id: uuid.UUID, db: Session = Depends(get_db)):
    return _entwurf_wechsel(aufstellung_id, db, True)



@router.post("/{aufstellung_id}/finalisieren")
def finalisiere_aufstellung(aufstellung_id: uuid.UUID, db: Session = Depends(get_db)):
    # Zeilensperre vor der teuren Zeile (Muster Rechnung, #6): Zwei Klicks
    # duerfen nicht zweimal Ghostscript starten; der zweite wartet bis zum
    # Commit des ersten und liest dann den neuen Status — saubere Absage
    # statt einer zweiten Pipeline ueber den fertigen Beleg hinweg.
    aufstellung = (
        db.query(Aufstellung)
        .filter(Aufstellung.id == aufstellung_id)
        .with_for_update()
        .first()
    )
    if not aufstellung:
        raise HTTPException(404)
    try:
        finalisieren(db, aufstellung, settings)
    except (FinalisierenFehler, StornoFehler) as fehler:
        # 400 mit Meldung: Der Mensch soll wissen, warum nichts gestellt
        # wurde — ein nackter Status waere "nochmal versuchen".
        raise HTTPException(400, str(fehler)) from fehler
    # Der Handgriff kehrt zur Detailseite des gestellten Belegs zurück.
    return RedirectResponse(url=f"/aufstellungen/{aufstellung_id}", status_code=303)


@router.get("/{aufstellung_id}/pdf")
def aufstellung_pdf_abrufen(aufstellung_id: uuid.UUID, db: Session = Depends(get_db)):
    aufstellung = db.query(Aufstellung).filter(Aufstellung.id == aufstellung_id).first()
    # Nur die GESTELLTE Aufstellung hat ein PDF: Ein Entwurf ist kein Beleg,
    # und ein Storno (7e) behaelt sein Archiv-Exemplar, liefert es aber nicht
    # als "die" Aufstellung aus.
    if not aufstellung or aufstellung.status != "issued" or not aufstellung.pdf_filename:
        raise HTTPException(404, "PDF nicht gefunden")
    pfad = settings.storage_path / "aufstellungen" / aufstellung.pdf_filename
    if not pfad.exists():
        raise HTTPException(404, "PDF-Datei nicht auf dem Server gefunden")
    return FileResponse(str(pfad), media_type="application/pdf",
                        filename=aufstellung.pdf_filename)


@router.post("/{aufstellung_id}/an-buchhaltung")
def an_buchhaltung(aufstellung_id: uuid.UUID, db: Session = Depends(get_db)):
    from app.services.aufstellung_versand import VersandFehler, senden
    from app.services.belegsprache import UnknownDocumentLanguageError
    from app.services.mailtext import BetreffMitZeilenumbruchError

    aufstellung = db.get(Aufstellung, aufstellung_id)
    if not aufstellung:
        raise HTTPException(404)
    try:
        senden(db, aufstellung, settings)
    except (VersandFehler, UnknownDocumentLanguageError, BetreffMitZeilenumbruchError) as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    return RedirectResponse(url=f"/aufstellungen/{aufstellung_id}", status_code=303)


@router.post("/{aufstellung_id}/stornieren")
def storniere_aufstellung(aufstellung_id: uuid.UUID, db: Session = Depends(get_db)):
    from sqlalchemy.exc import IntegrityError
    from app.services.aufstellung_storno import StornoFehler, entwurf_anlegen

    original = db.get(Aufstellung, aufstellung_id)
    if not original:
        raise HTTPException(404)
    try:
        storno = entwurf_anlegen(db, original)
        db.commit()
    except StornoFehler as fehler:
        db.rollback()
        raise HTTPException(400, str(fehler)) from fehler
    except IntegrityError as fehler:
        db.rollback()
        if getattr(getattr(fehler.orig, "diag", None), "constraint_name", None) != (
            "uq_aufstellungen_ein_aktives_storno_pro_original"
        ):
            raise
        raise HTTPException(400, "Zu dieser Aufstellung besteht bereits ein Storno.") from fehler
    return RedirectResponse(url=f"/aufstellungen/{storno.id}", status_code=303)
