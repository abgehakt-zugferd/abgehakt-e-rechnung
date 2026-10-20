import os
import tempfile
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.app_config import AppConfig
from app.models.company import Company
from app.models.invoice import Invoice, ValidationResult
from app.routers.invoices.abbildung import firma_laden
from app.routers.invoices.vorlagen import templates
from app.services import aenderungsprotokoll, datev_email, pdf_generator, zugferd_xml
from app.services.belegart import UnknownInvoiceTypeError, belegart
from app.services.einheiten import UnknownUnitError
from app.services.ersatzrechnung import ErsatzNichtMoeglich, pruefe_ersetzbar
from app.services.rechnung.pruefung import run_validation
from app.zeit import heute, kalendertag

router = APIRouter()


def _cc_vorbelegung(invoice: Invoice, app_config) -> tuple[str, str]:
    """Vorbelegung des CC-Feldes und ihre Herkunft (#58).

    Vorrangkette, ausdruecklich keine Vereinigung: liegt beim Kunden eine Liste,
    gilt allein sie. Wuerde die globale Voreinstellung dazugemischt, liesse sie
    sich fuer einen einzelnen Kunden nie mehr abwaehlen, ohne sie ueberall zu
    loeschen. Ein leeres Kundenfeld heisst „nichts hinterlegt", nicht
    „ausdruecklich keine Kopie" — deshalb erbt es die Voreinstellung.

    Die Herkunft geht mit in die Oberflaeche, weil ein vorbelegtes Feld sonst
    nicht erklaert, wem die Kopie zu verdanken ist und was ein Ueberschreiben
    aendert (naemlich nur diesen einen Versand).
    """
    kunde = invoice.customer
    if kunde is not None and kunde.cc_emails:
        return kunde.cc_emails, "kunde"
    voreinstellung = (app_config.invoice_cc_email if app_config else "") or ""
    if voreinstellung:
        return voreinstellung, "einstellungen"
    return "", ""


def _kunde_zustellung_fuer_detail(invoice: Invoice) -> tuple[date | None, str | None]:
    """Datum und Weg der Kundenzustellung fuer die Zeile auf der Detailseite.

    Gezeigt wird die JUENGSTE Zustellung, nicht die erste: Ein weiterer Vermerk
    ist die Korrektur, und die Leserin soll den korrigierten Stand sehen. Das
    Modell liefert `send_logs` neueste zuerst, also genuegt der erste Treffer.
    Gezaehlt werden nur GELUNGENE Versuche: Ein Fehlversand ist keine Zustellung
    (sonst stuende hier „zugestellt", waehrend der Beleg als „Nicht versendet"
    gilt). Fallback ohne jede Protokollzeile ist `kunde_zugestellt_am` selbst —
    so zeigen auch rueckwirkend gesicherte Belege (Migration) ein Datum.
    """
    for log in invoice.send_logs:
        if log.success is not True:
            continue
        if log.ziel == "kunde_vermerk":
            return kalendertag(log.sent_at), log.weg_notiz
        if log.ziel == "kunde_und_buchhaltung":
            return kalendertag(log.sent_at), "per Mail"
    if invoice.kunde_zugestellt_am is not None:
        return kalendertag(invoice.kunde_zugestellt_am), None
    return None, None


def _ersetzbarkeit(db: Session, invoice: Invoice) -> tuple[bool, bool]:
    """(Beleg ersetzbar, Original der Gutschrift ersetzbar) für die Knöpfe der Detailseite."""
    # Knopf nur, wenn das Anlegen auch durchginge: dieselbe Regel, keine zweite.
    # Ein unbekannter gespeicherter Typ ist kein ersetzbarer Beleg, aber die
    # Detailseite muss ihn trotzdem zeigen (Befund 1: nie 500 auf den Bestand).
    try:
        pruefe_ersetzbar(db, invoice.id)
        ersetzbar = True
    except (ErsatzNichtMoeglich, UnknownInvoiceTypeError):
        ersetzbar = False
    # Gutschrift (#142): statt "stornieren" den Weg zur Ersatzrechnung zeigen,
    # wenn sie fuer das Original angelegt werden kann.
    original_ersetzbar = False
    try:
        ist_gutschrift = belegart(invoice.invoice_type).intern == "credit_note"
    except UnknownInvoiceTypeError:
        ist_gutschrift = False
    if ist_gutschrift and invoice.original_invoice_id:
        try:
            pruefe_ersetzbar(db, invoice.original_invoice_id)
            original_ersetzbar = True
        except ErsatzNichtMoeglich:
            pass
    return ersetzbar, original_ersetzbar


def _detail_kontext(db: Session, invoice: Invoice) -> dict:
    """Alles, was `invoices/detail.html` neben `request` braucht."""
    company = db.query(Company).filter(Company.id == 1).first()
    latest_validation = (
        db.query(ValidationResult)
        .filter(ValidationResult.invoice_id == invoice.id)
        .order_by(ValidationResult.validated_at.desc())
        .first()
    )
    cfg = datev_email._get_effective_smtp_config(db)
    # CC-Vorbelegung (#147) kommt allein aus der DB — kein .env-Gegenpart, deshalb
    # nicht über EffectiveSettings.
    app_config = db.query(AppConfig).filter(AppConfig.id == 1).first()
    cc_default, cc_herkunft = _cc_vorbelegung(invoice, app_config)
    ersetzbar, original_ersetzbar = _ersetzbarkeit(db, invoice)
    kunde_zustellung_am, kunde_weg = _kunde_zustellung_fuer_detail(invoice)
    return {
        "invoice": invoice,
        "company": company,
        "validation": latest_validation,
        "datev_configured": bool(cfg.datev_bcc_email),
        "smtp_configured": bool(cfg.smtp_host),
        "cc_default": cc_default,
        "cc_herkunft": cc_herkunft,
        "protokoll": aenderungsprotokoll.protokoll_fuer(db, invoice.id),
        "heute": heute(),
        "ersetzbar": ersetzbar,
        "original_ersetzbar": original_ersetzbar,
        "kunde_zustellung_am": kunde_zustellung_am,
        "kunde_weg": kunde_weg,
    }


@router.get("/{invoice_id}", response_class=HTMLResponse)
def invoice_detail(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Rechnung nicht gefunden")
    return templates.TemplateResponse(
        "invoices/detail.html", {"request": request, **_detail_kontext(db, invoice)})


def _get_draft_for_preview(db: Session, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Rechnung nicht gefunden")
    if invoice.status != "draft":
        raise HTTPException(
            400,
            "Eine Vorschau gibt es nur für Entwürfe. Für diese Rechnung existiert das "
            "echte Dokument unter /invoices/{}/pdf.".format(invoice_id),
        )
    return invoice


@router.get("/{invoice_id}/vorschau", response_class=HTMLResponse)
def preview_page(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    invoice = _get_draft_for_preview(db, invoice_id)
    # Ohne Verkäuferdaten wäre die Vorschau irreführend.
    company = firma_laden(db)
    try:
        xml = zugferd_xml.generate_xml(invoice, company)
    except (UnknownUnitError, ValueError) as fehler:
        raise HTTPException(400, str(fehler)) from fehler
    return templates.TemplateResponse("invoices/preview.html", {
        "request": request,
        "invoice": invoice,
        "company": company,
        # NUR ans Template — nicht an `invoice.zugferd_xml`. Die Vorschau erzeugt
        # keinen Beleg, sie zeigt nur, was beim Finalisieren entstünde.
        "xml": xml,
    })


@router.get("/{invoice_id}/vorschau.pdf")
def preview_pdf(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    invoice = _get_draft_for_preview(db, invoice_id)
    company = firma_laden(db)

    # Ein Brief ohne Anschrift ist kein Brief: `generate_pdf` besteht zu Recht auf einem
    # Empfänger und wirft sonst `ValueError`. Seit ein Entwurf ohne Kunden erlaubt ist,
    # ist dieser Fall aber normal und kein Programmfehler — er gehört als Satz beantwortet
    # und nicht als 500er mit Stapelspur. Die XML-Vorschau daneben kommt ohne Kunden aus.
    if not invoice.customer:
        raise HTTPException(
            400,
            "Für die PDF-Vorschau fehlt der Kunde: ohne Empfänger gibt es keine "
            "Anschrift. Kunde zuweisen, dann erscheint die Vorschau.",
        )

    # Wegwerf-Datei statt `storage/pdfs/`: das ist das GoBD-Archiv. Ein Vorschau-PDF
    # dort wäre später von einem echten Beleg nicht zu unterscheiden und würde unter
    # dem Namen `<Rechnungsnummer>.pdf` mit dem echten kollidieren.
    fd, tmp_name = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        # Der Generator loest Belegart und Einheiten selbst auf und wirft bei
        # unbekannten Werten. Ohne diesen Zweig antwortet die Vorschau mit 500,
        # waehrend HTML- und XML-Vorschau denselben Fall als 400 melden.
        try:
            pdf_generator.generate_pdf(invoice, company, tmp_path, draft=True)
        except (UnknownInvoiceTypeError, UnknownUnitError) as fehler:
            raise HTTPException(400, str(fehler)) from None
        daten = tmp_path.read_bytes()
    finally:
        tmp_path.unlink(missing_ok=True)

    return Response(
        content=daten,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{invoice.invoice_number}_ENTWURF.pdf"'},
    )


@router.post("/{invoice_id}/pruefen")
def validate_invoice_route(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404)
    company = firma_laden(db)

    run_validation(db, invoice, company)
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)
