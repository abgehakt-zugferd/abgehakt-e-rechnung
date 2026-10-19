import uuid

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.invoice import Invoice
from app.services.rechnung import versand as dienst
from app.services.rechnung.fehler import RechnungFehler

router = APIRouter()


def _rechnung_laden(db: Session, invoice_id: uuid.UUID, detail: str | None = None) -> Invoice:
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, detail)
    return invoice


@router.post("/{invoice_id}/datev-senden")
def send_to_datev(invoice_id: uuid.UUID, customer_email: str = Form(""),
                  cc_email: str = Form(""), db: Session = Depends(get_db)):
    invoice = _rechnung_laden(db, invoice_id)
    try:
        to_email = dienst.empfaenger_adresse(invoice, customer_email)
        dienst.an_kunde_und_buchhaltung(db, invoice, to_email, cc_email)
    except RechnungFehler as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/an-buchhaltung")
def send_an_buchhaltung(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    """Nur an die Buchhaltung (Entscheidung 6): Mail allein an die Upload-Adresse,
    neutrale Schablone ohne Kundenanrede (Festlegung 16), keine Blindkopie und
    kein CC — der Kunde bleibt offen, kunde_zugestellt_am bleibt unberührt."""
    invoice = _rechnung_laden(db, invoice_id)
    try:
        dienst.an_buchhaltung(db, invoice)
    except RechnungFehler as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/zustellung-vermerken")
def zustellung_vermerken(
    invoice_id: uuid.UUID,
    datum: str = Form(""),
    weg: str = Form(""),
    db: Session = Depends(get_db),
):
    """Zustellung an den Kunden von Hand vermerken (Bauschritt 5b, Teil 2).

    Nicht jede Zustellung geht durch dieses Programm: Upload in ein Kunden-
    portal, Aushaendigung, Fax. Der Vermerk zeichnet so einen Vorgang NACH und
    ist die Behauptung des Nutzers, nicht das Ergebnis eines Versands — deshalb
    kein SMTP, keine Versandgrundlage (`pruefe_versandgrundlage` prueft das
    PDF auf dem Weg zu einem VERSAND; der Beleg wurde ausserhalb bereits
    zugesellt) und `success = True` im Protokoll.
    """
    invoice = _rechnung_laden(db, invoice_id, "Rechnung nicht gefunden")
    try:
        tag, weg = dienst.zustellung_eingabe(invoice, datum, weg)
        dienst.zustellung_vermerken(db, invoice, tag, weg)
    except RechnungFehler as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)
