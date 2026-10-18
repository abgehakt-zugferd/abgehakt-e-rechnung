"""Handgriffe der Abrechnungsaufstellung (§ 8b, Bauschritte 7c bis 7e).

Liste und Detailseiten kommen mit 7g — jetzt gibt es nur den Handgriff,
der den Entwurf stellt, Versand, Storno und das archivierte PDF. Kein XML-Weg,
kein E-Rechnungs-Endpoint: Die Aufstellung ist KEINE Rechnung.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.aufstellung import Aufstellung
from app.services.aufstellung_finalisieren import FinalisierenFehler, finalisieren
from app.services.aufstellung_storno import StornoFehler

router = APIRouter()
settings = get_settings()


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
    # 7g bringt die Detailseite; dahin kehrt der Handgriff zurueck.
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
