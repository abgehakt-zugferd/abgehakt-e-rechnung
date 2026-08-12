"""GoBD-Datenexport (Z3): Formular-Seite + ZIP-Download pro Zeitraum."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import AuditLog, Invoice
from app.services.gobd_export import build_gobd_export
from app.branding import register_branding_globals
from app.darstellung import registriere_darstellungsfilter

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)


@router.get("/", response_class=HTMLResponse)
def export_page(request: Request):
    today = date.today()
    return templates.TemplateResponse("export/index.html", {
        "request": request,
        "default_von": date(today.year, 1, 1).isoformat(),
        "default_bis": today.isoformat(),
    })


@router.get("/gobd")
def download_gobd(von: date, bis: date, db: Session = Depends(get_db)):
    if bis < von:
        raise HTTPException(400, "Das Enddatum darf nicht vor dem Startdatum liegen.")

    invoices = (
        db.query(Invoice)
        .filter(Invoice.status != "draft",
                Invoice.issue_date >= von,
                Invoice.issue_date <= bis)
        .order_by(Invoice.invoice_number)
        .all()
    )
    customer_ids = {inv.customer_id for inv in invoices}
    customers = (
        db.query(Customer).filter(Customer.id.in_(customer_ids)).order_by(Customer.customer_number).all()
        if customer_ids else []
    )
    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.changed_at >= von,
                AuditLog.changed_at < bis + timedelta(days=1))
        .order_by(AuditLog.changed_at)
        .all()
    )

    settings = get_settings()
    zip_bytes = build_gobd_export(
        invoices=invoices, customers=customers, audit_rows=audit_rows,
        storage_path=settings.storage_path, date_from=von, date_to=bis,
        # GDPdU-Datenlieferant ist die eigene Firma, nicht die Software (#99 §4.4)
        company=db.query(Company).filter(Company.id == 1).first(),
    )
    filename = f"gobd-export_{von.isoformat()}_{bis.isoformat()}.zip"
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
