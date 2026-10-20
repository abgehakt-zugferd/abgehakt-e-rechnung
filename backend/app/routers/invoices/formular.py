import uuid
from datetime import timedelta
from types import SimpleNamespace

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.company import Company
from app.models.invoice import Invoice
from app.routers.invoices.abbildung import firma_laden
from app.routers.invoices.formular_bearbeiten import (
    FormularFehler,
    beleg_binden,
    belegart_aendern,
    ersatzbezug_sperren,
    kopf_uebernehmen,
    kundenvorgabe_nachtragen,
    positionsangaben_pruefen,
    summen_aus_formular,
)
from app.routers.invoices.formular_lesen import belegart_waehlbar, items_as_json
from app.routers.invoices.formular_schreiben import (
    entwurf_laden,
    ersatz_anwenden,
    ersetzt_id_pruefen,
    kopfdaten_lesen,
    leerer_formularzustand,
    positionen_und_summen_pruefen,
    positionen_ersetzen,
    summen_schreiben,
    vorlage_anwenden,
    waehlbare_kunden,
)
from app.routers.invoices.vorlagen import templates
from app.services.invoice_number import generate_next_invoice_number
from app.services.leistungszeit import parse_leistungszeit_from_form
from app.services.rechnung.pruefung import run_validation
from app.zeit import heute

router = APIRouter()


def _neues_formular(request: Request, customers, company, today, delivery_default,
                    zustand: SimpleNamespace, *, ersetzt_angefragt: bool):
    # Die Spec verlangt 404 oder Redirect mit Fehlertext. Ein 200 auf eine
    # ungueltige Vorlagenkennung sagt dem Aufrufer, es sei alles in Ordnung; das
    # Formular ist dann leer, und niemand weiss, warum.
    # Status bei Fehler: 400 wenn `?ersetzt=` gesetzt war (auch wenn der Beleg
    # nicht ladbar ist), sonst 404 — wie zuvor an `ersetzt is not None`.
    return templates.TemplateResponse("invoices/form.html", {
        "request": request,
        "invoice": None,
        "vorbelegung": zustand.vorbelegung,
        "items_json": zustand.items_json,
        "customers": customers,
        "company": company,
        "today": today.isoformat(),
        "due_default": (today + timedelta(days=14)).isoformat(),
        "delivery_default": delivery_default,
        # Belegart-Feld: Neuanlage bietet immer die manuelle Auswahl; die
        # Vorbelegung traegt die Belegart der Vorlage nie (Feldvertrag
        # docs/specs/kopieren.md) — das Formular startet bei Standard.
        "belegart_waehlbar": True,
        "error": zustand.error,
        "kunde_hinweis": zustand.kunde_hinweis,
        "ersetzt": zustand.ersetzt_beleg,
    }, status_code=(400 if ersetzt_angefragt else 404) if zustand.error else 200)


@router.get("/neu", response_class=HTMLResponse)
def new_invoice_form(
    request: Request,
    db: Session = Depends(get_db),
    vorlage: str | None = None,
    ersetzt: str | None = None,
):
    customers = waehlbare_kunden(db)
    company = db.query(Company).filter(Company.id == 1).first()
    today = heute()
    # invoice bleibt immer None: gesetzt wuerde das Formular auf die Vorlage speichern.
    # Vorbelegung ist eine eigene Kontextgroesse (docs/specs/kopieren.md).
    zustand = leerer_formularzustand()

    # `is not None`, nicht `if vorlage`: `?vorlage=` ist eine gestellte Frage mit
    # unbrauchbarer Kennung, kein fehlender Parameter. Sie lief bisher als stille
    # Neuanlage durch (docs/specs/kopieren.md verlangt einen sichtbaren Hinweis).
    if vorlage is not None:
        vorlage_anwenden(db, vorlage, customers, zustand)

    # Ersatzrechnung (docs/specs/ersatzrechnung.md): Vorbelegung wie beim Kopieren,
    # dazu Bezug und, anders als beim Kopieren, die Belegart des Originals.
    if ersetzt is not None:
        ersatz_anwenden(db, ersetzt, customers, zustand)

    delivery_default = today.isoformat()
    if zustand.vorbelegung and getattr(zustand.vorbelegung, "delivery_date", None):
        delivery_default = zustand.vorbelegung.delivery_date.isoformat()

    response = _neues_formular(
        request, customers, company, today, delivery_default, zustand,
        ersetzt_angefragt=ersetzt is not None,
    )
    # Nach dem Absenden liegt der History-Eintrag dieses Formulars direkt hinter der
    # Detailseite. Ohne `no-store` gibt der Browser ihn beim Zurück-Button gefüllt aus
    # dem Cache zurück — er sähe aus wie ein Editor für den gerade gespeicherten
    # Entwurf, wäre aber weiter `action="/invoices/neu"` und legte beim Absenden eine
    # zweite Rechnung mit neuer Nummer an (nach GoBD nicht mehr löschbar). Den
    # bfcache-Pfad, bei dem der Server gar nicht gefragt wird, deckt die
    # Zurück-Erkennung in `form.html` ab.
    response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/neu")
async def create_invoice(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    company = firma_laden(db)
    kopf = kopfdaten_lesen(db, form, company)
    positionen, summen, abzug_betrag, abzug_grund = positionen_und_summen_pruefen(form)
    ersetzt_id = ersetzt_id_pruefen(db, form)

    invoice_number = generate_next_invoice_number(db, issue_date=kopf["issue_date"])

    invoice = Invoice(
        invoice_number=invoice_number,
        currency="EUR",
        zugferd_profile="EN16931",
        ersetzt_invoice_id=ersetzt_id,
        **kopf,
    )
    db.add(invoice)
    db.flush()

    positionen_ersetzen(db, invoice, positionen)
    summen_schreiben(invoice, summen, abzug_betrag, abzug_grund)

    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice.id}", status_code=303)


def _bearbeiten_antwort(request: Request, db: Session, invoice: Invoice,
                        meldung: str | None, **antwort):
    return templates.TemplateResponse("invoices/form.html", {
        "request": request,
        "invoice": invoice,
        "vorbelegung": None,
        "items_json": items_as_json(invoice),
        "customers": waehlbare_kunden(db),
        "company": db.query(Company).filter(Company.id == 1).first(),
        "today": heute().isoformat(),
        "due_default": invoice.due_date.isoformat() if invoice.due_date else "",
        "delivery_default": heute().isoformat(),
        "belegart_waehlbar": belegart_waehlbar(invoice),
        "error": meldung,
    }, **antwort)


@router.get("/{invoice_id}/bearbeiten", response_class=HTMLResponse)
def edit_invoice_form(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    invoice = entwurf_laden(db, invoice_id)
    return _bearbeiten_antwort(request, db, invoice, None)


def _bearbeiten_mit_fehler(request: Request, db: Session, invoice: Invoice, meldung: str):
    """Das Formular noch einmal, mit Meldung. 400, weil nichts gespeichert wurde."""
    db.rollback()
    return _bearbeiten_antwort(request, db, invoice, meldung, status_code=400)


def _eingaben_uebernehmen(db: Session, invoice: Invoice, company: Company, form):
    """Alle Formularwerte in den Entwurf schreiben; liefert Positionen und Summen."""
    delivery_date, service_period_start, service_period_end = (
        parse_leistungszeit_from_form(form))
    ersatzbezug_sperren(form)
    belegart_aendern(invoice, form)
    rohe_positionen, aus_beleg, kunde_vorher = beleg_binden(
        db, invoice, form, service_period_start, service_period_end)
    positionsangaben_pruefen(rohe_positionen)
    kopf_uebernehmen(invoice, form, company, delivery_date, aus_beleg)
    kundenvorgabe_nachtragen(db, invoice, kunde_vorher)
    return summen_aus_formular(form, rohe_positionen)


@router.post("/{invoice_id}/bearbeiten")
async def update_invoice(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    invoice = entwurf_laden(db, invoice_id)
    company = firma_laden(db)
    form = await request.form()

    try:
        positionen, summen, abzug_betrag, abzug_grund = _eingaben_uebernehmen(
            db, invoice, company, form)
    except FormularFehler as fehler:
        return _bearbeiten_mit_fehler(request, db, invoice, fehler.meldung)

    positionen_ersetzen(db, invoice, positionen)
    summen_schreiben(invoice, summen, abzug_betrag, abzug_grund)

    # Nachprüfen mit den NEUEN Positionen: `positionen_ersetzen` hat sie erst in die Session
    # gelegt, die geladene `items`-Beziehung zeigt sonst noch den alten Stand.
    db.flush()
    db.expire(invoice, ["items"])
    run_validation(db, invoice, company)

    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)
