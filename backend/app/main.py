import http
import mimetypes
import warnings
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from fastapi import FastAPI, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.database import get_db
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.routers import (
    customers, invoices, settings as settings_router, export, setup,
    updates, archive,
)
from app.dependencies.herkunft import pruefe_herkunft
from app.dependencies.update_banner_dep import load_update_banner
from app.config import get_settings
from app.services.audit import register_audit_listeners
from app.services.customer_guard import register_customer_guard
from app.services.invoice_guard import register_invoice_guard
from app.branding import PRODUCT_NAME, register_branding_globals
from app.darstellung import registriere_darstellungsfilter

# GoBD: Statusmaschinen-Guards + Audit-Log — Registrierung beim App-Import,
# damit ausnahmslos jede Session (Web, Skripte) erfasst wird.
# Guards ZUERST: sie müssen werfen, bevor der Audit-Listener Pending-Einträge sammelt
# (sonst Geister-Audit-Zeilen beim nächsten Flush nach einem Rollback).
register_invoice_guard()
register_customer_guard()
register_audit_listeners()


# === Startup Validation ===
# Prüft kritische Konfigurationen beim Start der Anwendung.

def validate_startup_config(settings) -> None:
    """Validiert essentielle Konfigurationen beim Anwendungsstart.

    P3: SECRET_KEY muss gesetzt sein (DSGVO/Sicherheit; u. a. Basis der
    Secret-Verschlüsselung at rest). Fehlt er, bricht der Boot bewusst ab.

    Im Normalbetrieb kann das nicht mehr passieren: die Settings holen den
    Schlüssel aus `storage/secret.key` bzw. legen ihn dort an (#99 §5.4). Der
    Check bleibt als letzte Reißleine — er greift, wenn jemand `SECRET_KEY=""`
    erzwingt oder das storage-Volume nicht beschreibbar ist. Deshalb nennt die
    Meldung auch nicht mehr die `.env`: die gibt es beim Piloten nicht.
    """
    if not settings.secret_key:
        raise RuntimeError(
            "SECRET_KEY fehlt und konnte nicht erzeugt werden. Erwartet wird die Datei "
            f"'{settings.storage_path}/secret.key' — ist das storage-Verzeichnis "
            "eingebunden und beschreibbar?"
        )
    if len(settings.secret_key) < 32:
        warnings.warn(
            "SECRET_KEY sollte mindestens 32 Zeichen lang sein für ausreichende Sicherheit.",
            UserWarning,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_startup_config(get_settings())
    yield


app = FastAPI(
    title=PRODUCT_NAME, docs_url=None, redoc_url=None, lifespan=lifespan,
    # App-weit statt in 10 TemplateResponse-Aufrufen: jeder Router hält eine
    # eigene Jinja2Templates-Instanz (siehe branding.py), base.html liest aus request.state.
    # `pruefe_herkunft` ZUERST: sie weist eine fremde Anfrage ab, bevor
    # irgendeine Route nachsieht, ob es den angefragten Datensatz gibt — sonst
    # verriete schon die Antwort (403 gegen 404), welche Kennungen vergeben sind.
    dependencies=[Depends(pruefe_herkunft), Depends(load_update_banner)],
)
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)

# Schriften und JavaScript kommen aus dem eigenen Image statt von fremden CDNs
# (siehe tests/test_oberflaeche_lokal.py).
#
# `mimetypes` kennt WOFF2 in einem schlanken Debian-Image nicht — ohne diese
# Zeile geht eine Binaerdatei als `text/plain` raus. Browser nehmen die Schrift
# trotzdem, aber alles, was dazwischenhaengt, darf Text anders behandeln als
# eine Schriftdatei.
#
# `mount` haengt eine Unteranwendung ein — die App-weite Abhaengigkeit oben
# (`load_update_banner`) laeuft dafuer bewusst NICHT: eine Datenbankabfrage je
# Schriftdatei waere reine Last ohne Nutzen.
mimetypes.add_type("font/woff2", ".woff2")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(customers.router, prefix="/customers", tags=["Kunden"])
app.include_router(invoices.router, prefix="/invoices", tags=["Rechnungen"])
app.include_router(settings_router.router, prefix="/settings", tags=["Einstellungen"])
app.include_router(export.router, prefix="/export", tags=["GoBD-Export"])
# Ohne Prefix: die Route heißt `/archiv` — mit Prefix + "/" würde jeder Aufruf von
# `/archiv` erst über einen 307 auf `/archiv/` laufen.
app.include_router(archive.router, tags=["Archiv"])
app.include_router(updates.router, prefix="/updates", tags=["Updates"])
app.include_router(setup.router, prefix="/setup", tags=["Ersteinrichtung"])


# Überschrift und Ersatztext je Statuscode. Starlette setzt ohne eigenen Text die
# englische Standardfloskel ein ("Not Found") — die hat vor einem deutschen
# Rechnungsprogramm nichts verloren.
_UEBERSCHRIFTEN = {
    400: "Das ging so nicht",
    403: "Nicht erlaubt",
    404: "Nicht gefunden",
    405: "Falscher Weg",
    413: "Zu groß",
    422: "Eingabe unvollständig",
}
_ERSATZTEXTE = {
    400: "Die Anfrage war nicht verwendbar. Bitte prüfen Sie Ihre Eingaben.",
    403: "Für diesen Vorgang fehlt die Berechtigung.",
    404: "Diese Seite oder dieser Datensatz wurde nicht gefunden. Möglicherweise "
         "wurde er verworfen oder die Adresse ist veraltet.",
    405: "Diese Adresse nimmt die verwendete Methode nicht entgegen.",
    413: "Die übermittelten Daten sind zu groß.",
    422: "Die übermittelten Felder waren unvollständig oder hatten ein "
         "unerwartetes Format.",
}


@app.exception_handler(StarletteHTTPException)
async def fehlerseite(request: Request, exc: StarletteHTTPException):
    """Abgewiesene Anfragen als Seite ausliefern statt als JSON.

    Rund 45 `raise HTTPException(...)` liegen in den Routern, und ihre Meldungen
    sind fachlich sorgfältig formuliert (§ 14 UStG, Statusmaschine, fail-closed).
    Als `{"detail": "..."}` auf weißem Grund erreichten sie den Menschen nicht:
    ein abgelehnter Formular-POST endete in einer geschweiften Klammer, ohne
    Navigation zurück.

    Bewusst OHNE Inhaltsaushandlung über den `Accept`-Kopf: die Anwendung hat
    keine Schnittstelle für Maschinen (kein `fetch` in den Vorlagen, `docs_url`
    ist abgeschaltet). Zwei Antwortformate hätten nur zur Folge, dass die Tests
    das Format prüfen, das der Mensch nie zu sehen bekommt.
    """
    meldung = exc.detail
    # Starlette füllt `detail` mit der englischen Standardfloskel, wenn beim
    # Werfen kein Text mitgegeben wurde (`HTTPException(404)`).
    if not meldung or meldung == http.HTTPStatus(exc.status_code).phrase:
        meldung = _ERSATZTEXTE.get(exc.status_code, "Die Anfrage konnte nicht "
                                                    "bearbeitet werden.")
    return templates.TemplateResponse(
        request,
        "fehler.html",
        {
            "status": exc.status_code,
            "ueberschrift": _UEBERSCHRIFTEN.get(exc.status_code, "Fehler"),
            "meldung": meldung,
        },
        status_code=exc.status_code,
        # `Allow` bei 405, `WWW-Authenticate` bei 401: die Köpfe gehören zur
        # Antwort, nicht zur Darstellung, und dürfen nicht verlorengehen.
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def eingabefehlerseite(request: Request, exc: RequestValidationError):
    """Pydantic-Eingabefehler ebenfalls als Seite.

    Ein zweiter Weg neben `HTTPException`: greift eine Feldprüfung von FastAPI
    (unlesbares Datum in `/export/gobd`, fehlendes Formularfeld), entsteht keine
    `HTTPException`, sondern ein `RequestValidationError`. Ohne diesen Behandler
    käme dieser Weg weiterhin als JSON heraus.

    Der Rohtext von Pydantic wird bewusst NICHT angezeigt: er ist englisch und
    nennt Feldpfade und interne Fehlertypen (`date_from_datetime_parsing`,
    `loc`). Das hilft niemandem, der eine Rechnung schreiben will.
    """
    felder = sorted({
        str(teil)
        for fehler in exc.errors()
        # Der erste Eintrag in `loc` ist die Herkunft ("query", "body"), nicht
        # der Feldname — er würde als Feldbezeichnung nur verwirren.
        for teil in fehler.get("loc", ())[1:]
        if isinstance(teil, str)
    })
    meldung = ("Die Eingabe war nicht verwendbar. Bitte prüfen Sie die Felder "
               "und versuchen Sie es erneut.")
    if felder:
        meldung += " Betroffen: " + ", ".join(felder) + "."
    return templates.TemplateResponse(
        request,
        "fehler.html",
        {"status": 422, "ueberschrift": _UEBERSCHRIFTEN[422], "meldung": meldung},
        status_code=422,
    )


@app.get("/", response_class=RedirectResponse)
def root():
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    company = db.query(Company).filter(Company.id == 1).first()
    # Ein Flag, keine Heuristik auf Feldinhalten (#99 §4.0): die frühere Prüfung
    # „keine Steuernummer und keine USt-IdNr." erklärte eine längst eingerichtete
    # Installation wieder für uneingerichtet, sobald jemand das Feld leerte.
    # Und ein Tor statt eines Hinweises: mit leeren Firmendaten weiterzuarbeiten
    # endet in Rechnungen ohne Verkäufer — im PDF wie in der ZUGFeRD-XML.
    if not setup.ist_eingerichtet(company):
        return RedirectResponse("/setup", status_code=303)

    today = date.today()
    first_of_month = today.replace(day=1)

    total_invoices = db.query(func.count(Invoice.id)).scalar() or 0
    open_invoices = db.query(func.count(Invoice.id)).filter(Invoice.status == "issued").scalar() or 0
    draft_count = db.query(func.count(Invoice.id)).filter(Invoice.status == "draft").scalar() or 0

    paid_this_month = (
        db.query(func.coalesce(func.sum(Invoice.gross_total), 0))
        .filter(Invoice.status == "paid", Invoice.issue_date >= first_of_month)
        .scalar()
    ) or Decimal("0")

    revenue_ytd = (
        db.query(func.coalesce(func.sum(Invoice.gross_total), 0))
        .filter(Invoice.status.in_(["issued", "paid"]), Invoice.issue_date >= today.replace(month=1, day=1))
        .scalar()
    ) or Decimal("0")

    recent_invoices = (
        db.query(Invoice)
        .join(Customer)
        .order_by(Invoice.issue_date.desc())
        .limit(10)
        .all()
    )

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "company": company,
        "total_invoices": total_invoices,
        "open_invoices": open_invoices,
        "draft_count": draft_count,
        "paid_this_month": paid_this_month,
        "revenue_ytd": revenue_ytd,
        "recent_invoices": recent_invoices,
    })
