"""Die zwei ersten Routen der Abrechnungsaufstellung (§ 8b, Bauschritt 7c).

Liste und Detailseiten kommen mit 7g — jetzt gibt es nur den Handgriff,
der den Entwurf stellt, und den Weg zum archivierten PDF. Kein XML-Weg,
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
    except FinalisierenFehler as fehler:
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
