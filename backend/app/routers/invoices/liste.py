from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.routers.invoices.vorlagen import templates
from app.services.rechnungsliste_filter import filtere_rechnungsliste

router = APIRouter()

# Wie viele Rechnungen eine Seite trägt. Bewusst eine Konstante und keine
# Einstellung: eine Zahl, die der Nutzer verstellen kann, ist eine Zahl, die
# irgendwann auf „alle" steht, und dann ist die Begrenzung wieder weg.
SEITENGROESSE = 50


@router.get("/", response_class=HTMLResponse)
def list_invoices(
    request: Request,
    db: Session = Depends(get_db),
    status: str = "",
    q: str = "",
    seite: int = 1,
    art: str = "",
    faellig: str = "",
    versand: str = "",
    storno: str = "",
):
    # `outerjoin`, nicht `join`: die Verbindung dient nur der Suche nach dem
    # Kundennamen. Ein INNER JOIN wuerde jeden Entwurf ohne Kunden (#141) lautlos
    # aus der Liste werfen — Status 200, Seite vollstaendig, Rechnung unauffindbar.
    query = db.query(Invoice).outerjoin(Customer)
    query, filtern = filtere_rechnungsliste(
        query, status=status, q=q, art=art, faellig=faellig, versand=versand,
        storno=storno,
    )

    # Gezählt wird in der Datenbank, geladen wird nur die Seite. Die Zahl unten
    # auf der geladenen Menge zu bilden, hieße das Problem zu verstecken statt es
    # zu lösen: „50 Rechnungen" wäre dann immer die Antwort.
    gesamt = query.order_by(None).count()
    seiten = max(1, -(-gesamt // SEITENGROESSE))
    seite = min(max(seite, 1), seiten)

    invoices = (query.options(joinedload(Invoice.customer))
                .order_by(Invoice.issue_date.desc())
                .offset((seite - 1) * SEITENGROESSE)
                .limit(SEITENGROESSE)
                .all())
    return templates.TemplateResponse("invoices/list.html", {
        "request": request, "invoices": invoices, "status_filter": status, "q": q,
        "art": filtern.art, "faellig": filtern.faellig, "versand": filtern.versand,
        "storno": filtern.storno,
        "seite": seite, "seiten": seiten, "gesamt": gesamt,
    })
