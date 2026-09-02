import uuid
from datetime import datetime, timezone
from urllib.parse import quote
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models.customer import Customer
from app.models.company import Company
from app.services.customer_number import next_customer_number
from app.services import empfaenger
from app.services.bankverbindung import normalisiere_bic, normalisiere_iban, pruefe_bic, pruefe_iban
from app.services.ust_id_pruefung import (
    eingaben_fuer_pruefung,
    normalisiere_ust_id,
    pruefe_ust_id_format,
    pruefe_ust_id_vies,
    speichern as ust_speichern,
    zuruecksetzen as ust_zuruecksetzen,
)
from app.services.adresse import bereinige_adresszeile2
from app.branding import register_branding_globals
from app.darstellung import registriere_darstellungsfilter

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)


def _render_form(request: Request, customer, suggested_number: str, values: dict, error: str | None,
                 company_vat_id: str | None = None):
    return templates.TemplateResponse("customers/form.html", {
        "request": request,
        "customer": customer,
        "suggested_number": suggested_number,
        "values": values,
        "error": error,
        "company_vat_id": company_vat_id,
    })


def _bank_felder(
    bank_iban: str,
    bank_bic: str,
    bank_name: str,
) -> tuple[dict, str | None]:
    """Normalisiert Bankfelder oder liefert Formularwerte + Fehlermeldung."""
    iban_fehler = pruefe_iban(bank_iban)
    if iban_fehler:
        return {
            "bank_iban": bank_iban,
            "bank_bic": bank_bic,
            "bank_name": bank_name,
        }, iban_fehler
    bic_fehler = pruefe_bic(bank_bic)
    if bic_fehler:
        return {
            "bank_iban": bank_iban,
            "bank_bic": bank_bic,
            "bank_name": bank_name,
        }, bic_fehler
    return {
        "bank_iban": bank_iban,
        "bank_bic": bank_bic,
        "bank_name": bank_name.strip(),
    }, None


def _bank_speichern(customer: Customer, felder: dict) -> None:
    customer.bank_iban = normalisiere_iban(felder.get("bank_iban"))
    customer.bank_bic = normalisiere_bic(felder.get("bank_bic"))
    customer.bank_name = (felder.get("bank_name") or "").strip() or None


def _number_taken(db: Session, number: str, exclude_id=None) -> bool:
    q = db.query(Customer).filter(Customer.customer_number == number)
    if exclude_id is not None:
        q = q.filter(Customer.id != exclude_id)
    return q.first() is not None


def _get_company(db: Session) -> Company | None:
    return db.query(Company).filter(Company.id == 1).first()


def _ust_id_verarbeiten(
    customer: Customer,
    roh_vat_id: str,
) -> tuple[str | None, str | None]:
    """Normalisiert USt-IdNr. und setzt Pruefstand zurueck bei Aenderung. Kein VIES-Abruf."""
    neu = normalisiere_ust_id(roh_vat_id) if (roh_vat_id or "").strip() else None
    if neu:
        fmt = pruefe_ust_id_format(neu)
        if fmt:
            return neu, fmt
    alt = customer.vat_id
    if not neu:
        ust_zuruecksetzen(customer)
        customer.vat_id = None
        return None, None
    if neu != alt:
        ust_zuruecksetzen(customer)
    customer.vat_id = neu
    return neu, None


@router.get("/", response_class=HTMLResponse)
def list_customers(request: Request, db: Session = Depends(get_db), q: str = ""):
    query = db.query(Customer).filter(Customer.deleted_at.is_(None))
    if q:
        query = query.filter(Customer.name.ilike(f"%{q}%"))
    customers = query.order_by(Customer.name).all()
    return templates.TemplateResponse("customers/list.html", {
        "request": request, "customers": customers, "q": q
    })


@router.get("/neu", response_class=HTMLResponse)
def new_customer_form(request: Request, db: Session = Depends(get_db)):
    response = _render_form(request, None, next_customer_number(db), {}, None)
    # Nach dem Absenden liegt der History-Eintrag dieses Formulars direkt hinter der
    # Kundenliste. Ohne `no-store` gibt der Browser ihn beim Zurück-Button gefüllt aus
    # dem Cache zurück und ein erneutes Speichern legt einen ZWEITEN Kunden mit neuer
    # Nummer an. Den bfcache-Pfad, bei dem der Server gar nicht gefragt wird, deckt das
    # Makro `partials/formular_zurueck_guard.html` in `form.html` ab.
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/neu")
def create_customer(
    request: Request,
    name: str = Form(...),
    customer_number: str = Form(""),
    address_line1: str = Form(...),
    address_line2: str = Form(""),
    zip_code: str = Form(...),
    city: str = Form(...),
    country: str = Form("DE"),
    vat_id: str = Form(""),
    email: str = Form(""),
    cc_emails: str = Form(""),
    phone: str = Form(""),
    bank_iban: str = Form(""),
    bank_bic: str = Form(""),
    bank_name: str = Form(""),
    notes: str = Form(""),
    is_active: str = Form("1"),
    db: Session = Depends(get_db),
):
    number = customer_number.strip() or next_customer_number(db)
    values = {
        "customer_number": number, "name": name, "address_line1": address_line1,
        "address_line2": address_line2, "zip_code": zip_code, "city": city,
        "country": country, "vat_id": vat_id, "email": email, "phone": phone, "notes": notes,
        "cc_emails": cc_emails,
    }
    bank_felder, bank_fehler = _bank_felder(bank_iban, bank_bic, bank_name)
    values.update(bank_felder)
    if bank_fehler:
        return _render_form(request, None, number, values, bank_fehler)
    cc_fehler = empfaenger.pruefe(cc_emails)
    if cc_fehler:
        return _render_form(request, None, number, values, cc_fehler)
    if _number_taken(db, number):
        return _render_form(request, None, number, values,
                            f"Kundennummer bereits vergeben: {number}")

    customer = Customer(
        customer_number=number,
        name=name.strip(),
        address_line1=address_line1.strip(),
        address_line2=bereinige_adresszeile2(name, address_line2),
        zip_code=zip_code.strip(),
        city=city.strip(),
        country=country.strip() or "DE",
        email=email.strip() or None,
        cc_emails=empfaenger.normalisiere(cc_emails) or None,
        phone=phone.strip() or None,
        notes=notes.strip() or None,
        is_active=(is_active == "1"),
    )
    _bank_speichern(customer, bank_felder)
    _, ust_fehler = _ust_id_verarbeiten(customer, vat_id)
    if ust_fehler:
        values["vat_id"] = customer.vat_id or vat_id
        return _render_form(request, None, number, values, ust_fehler)
    db.add(customer)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return _render_form(request, None, number, values,
                            f"Kundennummer bereits vergeben: {number}")
    return RedirectResponse(url="/customers", status_code=303)


@router.get("/{customer_id}/bearbeiten", response_class=HTMLResponse)
def edit_customer_form(customer_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                       vies_error: str = ""):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "Kunde nicht gefunden")
    company = _get_company(db)
    return _render_form(
        request, customer, "", {},
        vies_error.strip() or None,
        company_vat_id=company.vat_id if company else None,
    )


@router.post("/{customer_id}/bearbeiten")
def update_customer(
    request: Request,
    customer_id: uuid.UUID,
    name: str = Form(...),
    customer_number: str = Form(""),
    address_line1: str = Form(...),
    address_line2: str = Form(""),
    zip_code: str = Form(...),
    city: str = Form(...),
    country: str = Form("DE"),
    vat_id: str = Form(""),
    email: str = Form(""),
    cc_emails: str = Form(""),
    phone: str = Form(""),
    bank_iban: str = Form(""),
    bank_bic: str = Form(""),
    bank_name: str = Form(""),
    notes: str = Form(""),
    is_active: str = Form("1"),
    db: Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "Kunde nicht gefunden")
    bank_felder, bank_fehler = _bank_felder(bank_iban, bank_bic, bank_name)
    if bank_fehler:
        values = bank_felder
        return _render_form(request, customer, "", values, bank_fehler)
    cc_fehler = empfaenger.pruefe(cc_emails)
    if cc_fehler:
        return _render_form(request, customer, "", {}, cc_fehler)
    number = customer_number.strip() or customer.customer_number
    if number != customer.customer_number and _number_taken(db, number, exclude_id=customer.id):
        return _render_form(request, customer, "", {},
                            f"Kundennummer bereits vergeben: {number}")
    customer.customer_number = number
    customer.name = name.strip()
    customer.address_line1 = address_line1.strip()
    customer.address_line2 = bereinige_adresszeile2(name, address_line2)
    customer.zip_code = zip_code.strip()
    customer.city = city.strip()
    customer.country = country.strip() or "DE"
    customer.email = email.strip() or None
    customer.cc_emails = empfaenger.normalisiere(cc_emails) or None
    customer.phone = phone.strip() or None
    customer.notes = notes.strip() or None
    customer.is_active = (is_active == "1")
    _bank_speichern(customer, bank_felder)
    _, ust_fehler = _ust_id_verarbeiten(customer, vat_id)
    if ust_fehler:
        return _render_form(request, customer, "", {"vat_id": customer.vat_id or vat_id}, ust_fehler)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        db.refresh(customer)
        return _render_form(request, customer, "", {},
                            f"Kundennummer bereits vergeben: {number}")
    return RedirectResponse(url="/customers", status_code=303)


@router.post("/{customer_id}/ust-id-pruefen")
def pruefe_customer_ust_id(
    request: Request,
    customer_id: uuid.UUID,
    bestaetigt: str = Form(default=""),
    check_vat_id: str = Form(default=""),
    check_name: str = Form(default=""),
    db: Session = Depends(get_db),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "Kunde nicht gefunden")
    if bestaetigt != "1":
        raise HTTPException(400, "Einwilligung erforderlich")
    vat, name, fehler = eingaben_fuer_pruefung(
        check_vat_id, customer.vat_id, check_name, customer.name,
    )
    if fehler:
        return RedirectResponse(
            url=f"/customers/{customer_id}/bearbeiten?vies_error={quote(fehler)}",
            status_code=303,
        )
    if vat != customer.vat_id:
        ust_zuruecksetzen(customer)
        customer.vat_id = vat
    company = _get_company(db)
    ergebnis = pruefe_ust_id_vies(
        vat,
        name,
        company.vat_id if company else None,
    )
    ust_speichern(customer, ergebnis)
    db.commit()
    return RedirectResponse(url=f"/customers/{customer_id}/bearbeiten", status_code=303)


@router.post("/{customer_id}/loeschen")
def delete_customer(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "Kunde nicht gefunden")
    customer.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return RedirectResponse(url="/customers", status_code=303)
