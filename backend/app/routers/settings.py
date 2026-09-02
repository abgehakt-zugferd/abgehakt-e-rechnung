from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.company import Company
from app.models.app_config import AppConfig
from app.services import datev_email, empfaenger
from app.services.invoice_number import pruefe_praefix
from app.services.ust_id_pruefung import (
    eingaben_fuer_pruefung,
    normalisiere_ust_id,
    pruefe_ust_id_format,
    pruefe_ust_id_vies,
    speichern as ust_speichern,
    zuruecksetzen as ust_zuruecksetzen,
)
from app.branding import register_branding_globals
from app.darstellung import registriere_darstellungsfilter

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)


def _get_or_create_company(db: Session) -> Company:
    company = db.query(Company).filter(Company.id == 1).first()
    if not company:
        company = Company(id=1)
        db.add(company)
        db.commit()
        db.refresh(company)
    return company


def _get_or_create_app_config(db: Session) -> AppConfig:
    config = db.query(AppConfig).filter(AppConfig.id == 1).first()
    if not config:
        config = AppConfig(id=1)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


@router.get("/", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db), saved: bool = False, error: str = ""):
    company = _get_or_create_company(db)
    config = _get_or_create_app_config(db)  # Template braucht ihn für die CC-Vorbelegung (#147)
    from app.config import get_settings
    cfg = get_settings()
    # Effektive Konfiguration (DB überschreibt .env) – das Template zeigt genau die Werte,
    # die auch beim Versand verwendet werden, statt DB und .env inkonsistent zu mischen.
    effective = datev_email._get_effective_smtp_config(db)
    return templates.TemplateResponse("settings/index.html", {
        "request": request,
        "company": company,
        "config": config,
        "effective": effective,
        "cfg": cfg,
        "saved": saved,
        "error": error,
    })


@router.post("/firma")
def save_company(
    request: Request,
    name: str = Form(...),
    address_line1: str = Form(...),
    address_line2: str = Form(""),
    zip_code: str = Form(...),
    city: str = Form(...),
    country: str = Form("DE"),
    tax_number: str = Form(""),
    vat_id: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    contact_name: str = Form(""),
    bank_iban: str = Form(""),
    bank_bic: str = Form(""),
    bank_name: str = Form(""),
    invoice_prefix: str = Form("RE"),
    invoice_year_in_number: str = Form("on"),
    payment_terms_default: str = Form(""),
    db: Session = Depends(get_db),
):
    # ZUERST prüfen, dann erst etwas setzen: der Präfix wird Teil des Dateinamens
    # im GoBD-Archiv (`storage/pdfs/{nummer}.pdf`). Ein Wert mit `/` oder `..`
    # schöbe den Beleg aus dem Archiv heraus, während die Datenbank „gestellt"
    # sagt. Würde erst am Ende geprüft, hingen die übrigen Zuweisungen bereits in
    # der Sitzung und ein späterer Commit an anderer Stelle nähme sie mit.
    if (meldung := pruefe_praefix(invoice_prefix)):
        return settings_page(request, db, saved=False, error=meldung)

    company = _get_or_create_company(db)
    alt_vat = company.vat_id
    neu_vat = normalisiere_ust_id(vat_id) if (vat_id or "").strip() else None
    if neu_vat:
        fmt = pruefe_ust_id_format(neu_vat)
        if fmt:
            return settings_page(request, db, saved=False, error=fmt)
    company.name = name.strip()
    company.address_line1 = address_line1.strip()
    company.address_line2 = address_line2.strip() or None
    company.zip_code = zip_code.strip()
    company.city = city.strip()
    company.country = country.strip() or "DE"
    company.tax_number = tax_number.strip() or None
    if not neu_vat:
        ust_zuruecksetzen(company)
        company.vat_id = None
    else:
        if neu_vat != alt_vat:
            ust_zuruecksetzen(company)
        company.vat_id = neu_vat
    company.email = email.strip() or None
    company.phone = phone.strip() or None
    company.contact_name = contact_name.strip() or None
    company.bank_iban = bank_iban.replace(" ", "").upper() or None
    company.bank_bic = bank_bic.strip().upper() or None
    company.bank_name = bank_name.strip() or None
    company.invoice_prefix = invoice_prefix.strip() or "RE"
    company.invoice_year_in_number = invoice_year_in_number == "on"
    company.payment_terms_default = payment_terms_default.strip() or "Zahlbar innerhalb von 14 Tagen nach Rechnungseingang ohne Abzug."
    db.commit()
    return RedirectResponse(url="/settings?saved=true", status_code=303)


@router.post("/ust-id-pruefen")
def pruefe_company_ust_id(
    request: Request,
    bestaetigt: str = Form(default=""),
    check_vat_id: str = Form(default=""),
    check_name: str = Form(default=""),
    db: Session = Depends(get_db),
):
    company = _get_or_create_company(db)
    if bestaetigt != "1":
        raise HTTPException(400, "Einwilligung erforderlich")
    vat, name, fehler = eingaben_fuer_pruefung(
        check_vat_id, company.vat_id, check_name, company.name,
    )
    if fehler:
        return settings_page(request, db, saved=False, error=fehler)
    if vat != company.vat_id:
        ust_zuruecksetzen(company)
        company.vat_id = vat
    ergebnis = pruefe_ust_id_vies(vat, name)
    ust_speichern(company, ergebnis)
    db.commit()
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/smtp")
def save_smtp(
    smtp_host: str = Form(""),
    smtp_port: int = Form(587),
    smtp_user: str = Form(""),
    smtp_password: str = Form(""),
    smtp_from: str = Form(""),
    # Default False: eine abgewählte HTML-Checkbox sendet kein Feld – nur so lässt
    # sich TLS über die UI wieder deaktivieren.
    smtp_use_tls: bool = Form(False),
    db: Session = Depends(get_db),
):
    config = _get_or_create_app_config(db)
    host = smtp_host.strip() if smtp_host else None
    config.smtp_host = host
    # Ohne Host gilt die DB-SMTP-Konfiguration als nicht gesetzt: auch den Port leeren,
    # damit die effektive Konfiguration sauber auf die .env zurückfällt (kein stale Port).
    config.smtp_port = smtp_port if host else None
    config.smtp_user = smtp_user.strip() if smtp_user else None
    if smtp_password:  # nur bei neuer Eingabe überschreiben – verschlüsselt ablegen
        from app.services import crypto
        config.smtp_password = crypto.encrypt(smtp_password)
    config.smtp_from = smtp_from.strip() if smtp_from else None
    config.smtp_use_tls = smtp_use_tls
    db.commit()
    return RedirectResponse(url="/settings?saved=true", status_code=303)


@router.post("/datev")
def save_datev(
    datev_bcc_email: str = Form(""),
    invoice_cc_email: str = Form(""),
    db: Session = Depends(get_db),
):
    # Vor dem Anlegen der Zeile prüfen (#58): eine abgelehnte Eingabe darf nichts
    # schreiben, auch nicht die DATEV-Adresse aus demselben Formular.
    cc_fehler = empfaenger.pruefe(invoice_cc_email)
    if cc_fehler:
        return RedirectResponse(url=f"/settings?error={cc_fehler}", status_code=303)
    config = _get_or_create_app_config(db)
    config.datev_bcc_email = datev_bcc_email.strip() if datev_bcc_email else None
    # Leer heißt „keine Kopie" — NULL, nicht der leere String (#147). Mehrere
    # Adressen sind zulässig (#58); gespeichert wird die kanonische Schreibweise.
    config.invoice_cc_email = empfaenger.normalisiere(invoice_cc_email) or None
    db.commit()
    return RedirectResponse(url="/settings?saved=true", status_code=303)


@router.post("/smtp-test")
def test_smtp(test_email: str = Form(...), db: Session = Depends(get_db)):
    try:
        datev_email.send_test_email(test_email, db)
        return RedirectResponse(url="/settings?saved=true", status_code=303)
    except datev_email.EmailError as e:
        return RedirectResponse(url=f"/settings?error={str(e)}", status_code=303)
