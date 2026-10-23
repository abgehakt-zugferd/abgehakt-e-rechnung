"""Ersteinrichtung (#4, #99 §4.1).

Die Einrichtung ist ein Tor, kein Hinweis: solange sie offen ist, führt der
Einstieg hierher. Ein wegklickbarer Banner auf dem Dashboard hätte die Nutzerin
mit leeren Firmendaten weiterarbeiten lassen — und leere Firmendaten stehen
anschließend im PDF und in der rechtlich maßgeblichen ZUGFeRD-XML.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.services.adresse import bereinige_adresszeile2
from app.services.bankverbindung import normalisiere_bic, normalisiere_iban, pruefe_bic, pruefe_iban
from app.branding import register_branding_globals
from app.darstellung import registriere_darstellungsfilter
from app.laender import registriere_laender_globals
from app.database import get_db
from app.models.company import Company
from app.services.ersteinrichtung import (
    ADRESS_PFLICHTFELDER,
    einrichtung_abschliessen,
    einrichtung_luecke,
)
from app.services.pflichtangaben import RECHTSFORMEN

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)
registriere_laender_globals(templates)

FREIE_FELDER = ("address_line2", "country", "tax_number", "vat_id",
                "email", "phone", "bank_iban", "bank_bic", "bank_name",
                "rechtsform", "sitz", "registergericht", "registernummer",
                "vertretung", "aufsichtsrat_vorsitz")


def _company(db: Session) -> Company | None:
    return db.query(Company).filter(Company.id == 1).first()


@router.get("", response_class=HTMLResponse)
def formular(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("setup/index.html", {
        "request": request,
        "company": _company(db),
        "rechtsformen": RECHTSFORMEN,
        "fehler": None,
    })


@router.post("")
async def speichern(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    werte = {feld: (form.get(feld) or "").strip()
             for feld in ADRESS_PFLICHTFELDER + FREIE_FELDER}

    probe = Company(**{feld: werte[feld] or None for feld in werte})
    probe.city = werte["city"]
    if (meldung := einrichtung_luecke(probe)):
        return _mit_fehler(request, db, werte, meldung)

    if (meldung := pruefe_iban(werte["bank_iban"])):
        return _mit_fehler(request, db, werte, meldung)
    if (meldung := pruefe_bic(werte["bank_bic"])):
        return _mit_fehler(request, db, werte, meldung)

    company = _company(db)
    if company is None:
        # Migration 001 legt die Zeile an; fehlt sie trotzdem, ist die Einrichtung
        # der richtige Ort, sie zu erzeugen — nicht der Ort zum Abstürzen.
        company = Company(id=1)
        db.add(company)
    for feld, wert in werte.items():
        if feld == "address_line2":
            wert = bereinige_adresszeile2(werte["name"], wert) or None
        elif feld == "bank_iban":
            wert = normalisiere_iban(wert)
        elif feld == "bank_bic":
            wert = normalisiere_bic(wert)
        else:
            wert = wert or None
        setattr(company, feld, wert)
    company.country = werte["country"] or "DE"
    einrichtung_abschliessen(company)
    db.commit()

    return RedirectResponse("/dashboard", status_code=303)


def _mit_fehler(request: Request, db: Session, werte: dict, meldung: str):
    """400 statt Redirect: die Einrichtung bleibt offen, die Eingaben stehen noch da."""
    return templates.TemplateResponse("setup/index.html", {
        "request": request,
        "company": _company(db),
        "werte": werte,
        "rechtsformen": RECHTSFORMEN,
        "fehler": meldung,
    }, status_code=400)
