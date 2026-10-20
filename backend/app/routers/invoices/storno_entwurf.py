import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.invoice import Invoice
from app.services import auftragsschluessel
from app.services.ersatzrechnung import ErsatzNichtMoeglich, pruefe_ersetzbar
from app.services.rechnung.fehler import RechnungFehler
from app.services.rechnung.storno import (
    entwurf_anlegen,
    gutschrift_konflikt_nach_integrity,
    pruefe_zurueckholbar,
)

router = APIRouter()


@router.post("/{invoice_id}/verwerfen")
def discard_draft(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    """Entwurf verwerfen (#145) — Status statt Hard-Delete.

    Verbindlich ist der `invoice_guard` (Session-Ebene); die Prüfung hier ist die
    freundliche Antwort (400 statt 500), nicht die Absicherung. Die Rechnungsnummer
    bleibt belegt: sie ist beim Anlegen des Entwurfs vergeben worden, und der
    verbliebene Datensatz ist das Einzige, was die Nummernlücke später erklärt.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Rechnung nicht gefunden")
    if invoice.status != "draft":
        raise HTTPException(
            400, "Nur Entwürfe können verworfen werden. Eine gestellte Rechnung "
            "bleibt erhalten — Korrektur nur per Storno.")
    invoice.status = "discarded"
    # Festlegung 12: Der verworfene Entwurf sperrt nicht weiter. Der Nachweis
    # bleibt stehen — das Zurueckholen nimmt die Sperre wieder auf, wenn
    # zwischenzeitlich kein anderer Beleg sie gezogen hat.
    auftragsschluessel.freigeben(invoice)
    db.commit()
    return RedirectResponse(url="/invoices", status_code=303)


def _belegt_durch_anderen(db: Session, invoice: Invoice) -> None:
    """Bricht mit 400 ab, wenn der Auftragsschluessel inzwischen anderweitig belegt ist."""
    belegt_durch = auftragsschluessel.dokument_zu(db, invoice.auftragsschluessel)
    if belegt_durch is not None:
        raise HTTPException(
            400,
            "Zu diesem Auftrag gibt es inzwischen einen anderen Beleg: "
            f"{belegt_durch}.",
        )


def _ersatzbezug_pruefen(db: Session, invoice: Invoice) -> None:
    # Ein zurueckgeholter Ersatz wird wieder aktiv; inzwischen kann ein anderer
    # Ersatz oder keine Gutschrift mehr da sein (docs/specs/ersatzrechnung.md).
    if invoice.ersetzt_invoice_id is not None:
        try:
            pruefe_ersetzbar(db, invoice.ersetzt_invoice_id)
        except ErsatzNichtMoeglich as fehler:
            raise HTTPException(400, str(fehler)) from fehler


def _auftragssperre_zurueckholen(db: Session, invoice: Invoice) -> None:
    # Festlegung 19: Ein verworfener Entwurf mit Auftragsschluessel nimmt seine
    # Sperre nur zurueck, wenn zwischenzeitlich kein anderer Beleg den
    # Schluessel gezogen hat. Die Vorabpruefung nimmt keine Sperre; den
    # Wettlauf schlaegt der partielle Unique-Index unten, und die Meldung ist
    # in beiden Faellen dieselbe.
    if invoice.auftragsschluessel is not None:
        _belegt_durch_anderen(db, invoice)
        auftragsschluessel.belegen(invoice, invoice.auftragsschluessel)


def _zurueckholen_committen(db: Session, invoice: Invoice) -> None:
    try:
        db.commit()
    except IntegrityError:
        # Zweite Schicht (Festlegung 19 / #178): Der Index sieht, was die
        # Pruefung oben ohne Sperre verpasst hat. Rollback nimmt die Sperre
        # zurueck; die Meldung entspricht der Vorabpruefung, kein HTTP 500
        # (Muster: der Gutschrift-Index in create_storno / `_speichern`).
        db.rollback()
        gutschrift_konflikt_nach_integrity(db, invoice)
        if invoice.auftragsschluessel is not None:
            _belegt_durch_anderen(db, invoice)
        raise


@router.post("/{invoice_id}/zurueckholen")
def restore_draft(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Rechnung nicht gefunden")
    if invoice.status != "discarded":
        raise HTTPException(400, "Nur verworfene Entwürfe können zurückgeholt werden.")
    try:
        if invoice.original_invoice_id is not None:
            pruefe_zurueckholbar(db, invoice)
        _ersatzbezug_pruefen(db, invoice)
        _auftragssperre_zurueckholen(db, invoice)
        invoice.status = "draft"
        _zurueckholen_committen(db, invoice)
    except RechnungFehler as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/storno")
def create_storno(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        storno = entwurf_anlegen(db, invoice_id)
    except RechnungFehler as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return RedirectResponse(url=f"/invoices/{storno.id}", status_code=303)
