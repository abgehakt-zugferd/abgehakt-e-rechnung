import uuid

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.invoice import Invoice
from app.services import auftragsschluessel, auftragszahlung
from app.services.bezahlt_am import (
    BezahltAmFehler,
    BezahltTrotzGutschrift,
    vorbereiten_bezahlt,
)
from app.services.rechnung.fehler import RechnungFehler
from app.services.rechnung.finalisieren import ausfuehren, entwurf_sperren
from app.services.storno import GutschriftNichtStornierbar, pruefe_stornierbar
from app.zeit import heute

router = APIRouter()
# Zweiter Router: PDF-Download und Statuswechsel stehen im Bestand NACH dem
# Versand. `include_router` in `__init__` haengt ihn dort ein.
status_router = APIRouter()
settings = get_settings()


@router.post("/{invoice_id}/finalisieren")
def finalize_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        ausfuehren(db, invoice_id)
    except RechnungFehler as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/zahlungshinweis-uebernehmen")
def zahlungshinweis_uebernehmen(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        invoice = entwurf_sperren(db, invoice_id)
        auftragszahlung.uebernehmen(invoice)
    except RechnungFehler as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@status_router.get("/{invoice_id}/pdf")
def download_pdf(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice or not invoice.pdf_filename:
        raise HTTPException(404, "PDF nicht gefunden")
    pdf_path = settings.storage_path / "pdfs" / invoice.pdf_filename
    if not pdf_path.exists():
        raise HTTPException(404, "PDF-Datei nicht auf dem Server gefunden")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=invoice.pdf_filename)


_VALID_TRANSITIONS: dict[str, set[str]] = {
    "paid": {"issued"},
    "cancelled": {"issued"},
}


def _statuswechsel_pruefen(db: Session, invoice: Invoice, new_status: str,
                           bezahlt_am: str | None) -> None:
    if new_status not in _VALID_TRANSITIONS:
        raise HTTPException(400, f"Ungültiger Zielstatus '{new_status}'.")
    if invoice.status not in _VALID_TRANSITIONS[new_status]:
        raise HTTPException(
            400,
            f"Übergang von '{invoice.status}' nach '{new_status}' ist nicht erlaubt."
        )

    if new_status == "paid":
        try:
            vorbereiten_bezahlt(db, invoice, bezahlt_am, heute=heute())
        except (BezahltAmFehler, BezahltTrotzGutschrift) as exc:
            raise HTTPException(400, str(exc)) from exc
    if new_status == "cancelled":
        # Freundliche Antwort mit dem richtigen Weg; verbindlich sperrt der
        # invoice_guard (Issue #142).
        try:
            pruefe_stornierbar(invoice)
        except GutschriftNichtStornierbar as exc:
            raise HTTPException(400, str(exc)) from exc


@status_router.post("/{invoice_id}/status")
def update_status(
    invoice_id: uuid.UUID,
    new_status: str = Form(...),
    bezahlt_am: str | None = Form(None),
    db: Session = Depends(get_db),
):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404)
    _statuswechsel_pruefen(db, invoice, new_status, bezahlt_am)

    invoice.status = new_status
    if new_status == "cancelled":
        # Festlegung 12: Der manuell stornierte Beleg sperrt den
        # Auftragsschluessel nicht weiter; der Nachweis bleibt. (Bezahlen
        # gibt nichts frei — der Beleg besteht ja weiter.)
        auftragsschluessel.freigeben(invoice)
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)
