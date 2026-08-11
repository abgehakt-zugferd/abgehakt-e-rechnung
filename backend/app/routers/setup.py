"""Ersteinrichtung (#4, #99 §4.1).

Die Einrichtung ist ein Tor, kein Hinweis: solange sie offen ist, führt der
Einstieg hierher. Ein wegklickbarer Banner auf dem Dashboard hätte die Nutzerin
mit leeren Firmendaten weiterarbeiten lassen — und leere Firmendaten stehen
anschließend im PDF und in der rechtlich maßgeblichen ZUGFeRD-XML.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.branding import register_branding_globals
from app.database import get_db
from app.models.company import Company

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)

PFLICHTFELDER = ("name", "address_line1", "zip_code", "city")
FREIE_FELDER = ("address_line2", "country", "tax_number", "vat_id",
                "email", "phone", "bank_iban", "bank_bic", "bank_name")


def _company(db: Session) -> Company | None:
    return db.query(Company).filter(Company.id == 1).first()


def ist_eingerichtet(company: Company | None) -> bool:
    return bool(company and company.setup_completed_at is not None)


@router.get("", response_class=HTMLResponse)
def formular(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("setup/index.html", {
        "request": request,
        "company": _company(db),
        "fehler": None,
    })


@router.post("")
async def speichern(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    werte = {feld: (form.get(feld) or "").strip()
             for feld in PFLICHTFELDER + FREIE_FELDER}

    fehlend = [feld for feld in PFLICHTFELDER if not werte[feld]]
    if fehlend:
        return _mit_fehler(request, db, werte,
                           "Bitte Firmenname und vollständige Anschrift angeben.")

    # § 14 UStG: die Rechnung braucht Steuernummer ODER USt-IdNr. Fehlt beides,
    # wäre jede spätere Rechnung fehlerhaft — und zwar unbemerkt, weil der
    # Validator erst beim Prüfen anschlägt.
    if not werte["tax_number"] and not werte["vat_id"]:
        return _mit_fehler(request, db, werte,
                           "Steuernummer oder USt-IdNr. ist für § 14 UStG erforderlich.")

    company = _company(db)
    if company is None:
        # Migration 001 legt die Zeile an; fehlt sie trotzdem, ist die Einrichtung
        # der richtige Ort, sie zu erzeugen — nicht der Ort zum Abstürzen.
        company = Company(id=1)
        db.add(company)
    for feld, wert in werte.items():
        setattr(company, feld, wert or None)
    company.country = werte["country"] or "DE"
    company.setup_completed_at = datetime.now(timezone.utc)
    db.commit()

    return RedirectResponse("/dashboard", status_code=303)


def _mit_fehler(request: Request, db: Session, werte: dict, meldung: str):
    """400 statt Redirect: die Einrichtung bleibt offen, die Eingaben stehen noch da."""
    return templates.TemplateResponse("setup/index.html", {
        "request": request,
        "company": _company(db),
        "werte": werte,
        "fehler": meldung,
    }, status_code=400)
