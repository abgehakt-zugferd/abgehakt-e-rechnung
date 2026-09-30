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
from app.services import kundenformular as kform
from app.services.ust_id_pruefung import (
    eingaben_fuer_pruefung,
    normalisiere_ust_id,
    pruefe_ust_id_format,
    pruefe_ust_id_vies,
    speichern as ust_speichern,
    zuruecksetzen as ust_zuruecksetzen,
)
from app.services.steuerstatus import UST_STATUS_UNGEKLAERT
from app.branding import register_branding_globals
from app.darstellung import registriere_darstellungsfilter
from app.laender import registriere_laender_globals

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)
registriere_laender_globals(templates)


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


def _stammdaten_und_steuer(
    customer: Customer,
    *,
    name, address_line1, address_line2, zip_code, city, country,
    email, cc_emails, phone, notes, is_active,
    ust_status, gutschriftempfaenger, tax_number,
) -> None:
    kform.stammdaten_setzen(
        customer, name=name, address_line1=address_line1,
        address_line2=address_line2, zip_code=zip_code, city=city,
        country=country, email=email, cc_emails=cc_emails, phone=phone,
        notes=notes, is_active=is_active,
    )
    kform.steuer_speichern(
        customer, ust_status=ust_status,
        gutschriftempfaenger=gutschriftempfaenger, tax_number=tax_number,
    )


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
    # no-store: sonst legt Zurueck + Speichern einen zweiten Kunden an (#bfcache).
    response = _render_form(request, None, next_customer_number(db), {}, None)
    response.headers["Cache-Control"] = "no-store"
    return response


def _kunde_anlegen(request, db, *, number, values, bank, stamm, steuer, vat_id):
    bank_felder, bank_fehler = bank
    if bank_fehler:
        return _render_form(request, None, number, values, bank_fehler)
    cc_fehler = empfaenger.pruefe(stamm["cc_emails"])
    if cc_fehler:
        return _render_form(request, None, number, values, cc_fehler)
    if _number_taken(db, number):
        return _render_form(request, None, number, values,
                            f"Kundennummer bereits vergeben: {number}")
    customer = Customer(customer_number=number)
    _stammdaten_und_steuer(customer, **stamm, **steuer)
    kform.bank_speichern(customer, bank_felder)
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


@router.post("/neu")
def create_customer(
    request: Request, db: Session = Depends(get_db),
    name: str = Form(...), customer_number: str = Form(""),
    address_line1: str = Form(...), address_line2: str = Form(""),
    zip_code: str = Form(...), city: str = Form(...), country: str = Form("DE"),
    vat_id: str = Form(""), tax_number: str = Form(""),
    ust_status: str = Form(UST_STATUS_UNGEKLAERT), gutschriftempfaenger: str = Form(""),
    email: str = Form(""), cc_emails: str = Form(""), phone: str = Form(""),
    bank_iban: str = Form(""), bank_bic: str = Form(""), bank_name: str = Form(""),
    notes: str = Form(""), is_active: str = Form("1"),
):
    number = customer_number.strip() or next_customer_number(db)
    values = kform.formularwerte(
        number=number, name=name, address_line1=address_line1,
        address_line2=address_line2, zip_code=zip_code, city=city,
        country=country, vat_id=vat_id, tax_number=tax_number,
        ust_status=ust_status, gutschriftempfaenger=gutschriftempfaenger,
        email=email, phone=phone, notes=notes, cc_emails=cc_emails,
    )
    bank = kform.bank_felder(bank_iban, bank_bic, bank_name)
    values.update(bank[0])
    stamm = dict(
        name=name, address_line1=address_line1, address_line2=address_line2,
        zip_code=zip_code, city=city, country=country, email=email,
        cc_emails=cc_emails, phone=phone, notes=notes, is_active=is_active,
    )
    steuer = dict(
        ust_status=ust_status, gutschriftempfaenger=gutschriftempfaenger,
        tax_number=tax_number,
    )
    return _kunde_anlegen(
        request, db, number=number, values=values, bank=bank,
        stamm=stamm, steuer=steuer, vat_id=vat_id,
    )


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


def _kunde_aktualisieren(request, db, customer, *, number, bank, stamm, steuer, vat_id):
    bank_felder, bank_fehler = bank
    if bank_fehler:
        return _render_form(request, customer, "", bank_felder, bank_fehler)
    cc_fehler = empfaenger.pruefe(stamm["cc_emails"])
    if cc_fehler:
        return _render_form(request, customer, "", {}, cc_fehler)
    if number != customer.customer_number and _number_taken(db, number, exclude_id=customer.id):
        return _render_form(request, customer, "", {},
                            f"Kundennummer bereits vergeben: {number}")
    customer.customer_number = number
    _stammdaten_und_steuer(customer, **stamm, **steuer)
    kform.bank_speichern(customer, bank_felder)
    _, ust_fehler = _ust_id_verarbeiten(customer, vat_id)
    if ust_fehler:
        return _render_form(
            request, customer, "", {"vat_id": customer.vat_id or vat_id}, ust_fehler,
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        db.refresh(customer)
        return _render_form(request, customer, "", {},
                            f"Kundennummer bereits vergeben: {number}")
    return RedirectResponse(url="/customers", status_code=303)


@router.post("/{customer_id}/bearbeiten")
def update_customer(
    request: Request, customer_id: uuid.UUID, db: Session = Depends(get_db),
    name: str = Form(...), customer_number: str = Form(""),
    address_line1: str = Form(...), address_line2: str = Form(""),
    zip_code: str = Form(...), city: str = Form(...), country: str = Form("DE"),
    vat_id: str = Form(""), tax_number: str = Form(""),
    ust_status: str = Form(UST_STATUS_UNGEKLAERT), gutschriftempfaenger: str = Form(""),
    email: str = Form(""), cc_emails: str = Form(""), phone: str = Form(""),
    bank_iban: str = Form(""), bank_bic: str = Form(""), bank_name: str = Form(""),
    notes: str = Form(""), is_active: str = Form("1"),
):
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise HTTPException(404, "Kunde nicht gefunden")
    stamm = dict(
        name=name, address_line1=address_line1, address_line2=address_line2,
        zip_code=zip_code, city=city, country=country, email=email,
        cc_emails=cc_emails, phone=phone, notes=notes, is_active=is_active,
    )
    steuer = dict(
        ust_status=ust_status, gutschriftempfaenger=gutschriftempfaenger,
        tax_number=tax_number,
    )
    return _kunde_aktualisieren(
        request, db, customer,
        number=customer_number.strip() or customer.customer_number,
        bank=kform.bank_felder(bank_iban, bank_bic, bank_name),
        stamm=stamm, steuer=steuer, vat_id=vat_id,
    )


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
