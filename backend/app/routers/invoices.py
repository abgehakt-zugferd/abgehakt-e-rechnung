import uuid
import json
import shutil
import tempfile
import os
from datetime import date, timedelta, timezone, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session, joinedload
from app.database import get_db
from app.models.customer import Customer
from app.models.company import Company
from app.models.invoice import Invoice, InvoiceItem, ValidationResult, InvoiceSendLog
from app.services.leistungszeit import parse_leistungszeit_from_form
from app.models.app_config import AppConfig
from app.services import (mustang, zugferd_xml, pdf_generator, pdfa, validator,
                          datev_email, aenderungsprotokoll)
from app.services.invoice_number import generate_next_invoice_number
from app.services import empfaenger
from app.services.archive_frist import berechne_archive_until
from app.config import get_settings
from app.branding import register_branding_globals
from app.darstellung import registriere_darstellungsfilter

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)
settings = get_settings()


def _get_company(db: Session) -> Company:
    c = db.query(Company).filter(Company.id == 1).first()
    # Die Existenz der Zeile beweist nichts: Migration 001 legt sie IMMER an, auf
    # einer frischen Installation ist sie leer. Ein reiner Existenz-Check hätte
    # eine Rechnung mit leerem Verkäufer erzeugt — im PDF und in der ZUGFeRD-XML,
    # die seit 2025 rechtlich maßgeblich ist.
    if not c or c.setup_completed_at is None:
        raise HTTPException(400, "Firmendaten nicht konfiguriert. Bitte zuerst die Ersteinrichtung abschließen.")
    return c


def _calc_item(quantity: Decimal, unit_price: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    net = (quantity * unit_price).quantize(Decimal("0.01"), ROUND_HALF_UP)
    tax = (net * tax_rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    gross = net + tax
    return net, tax, gross


def _kunde_id(form) -> uuid.UUID | None:
    """Kunde aus dem Formular, oder None.

    Steht im Auswahlfeld noch „– Kunde wählen –", schickt der Browser einen LEEREN
    String mit, nicht gar nichts. `uuid.UUID("")` wirft dafür `ValueError` und damit
    einen 500er, wo eigentlich ein erlaubter Zustand vorliegt: ein Entwurf ohne
    Empfänger. Pflicht wird der Kunde erst beim Finalisieren (`BUYER_MISSING`).
    """
    roh = (form.get("customer_id") or "").strip()
    return uuid.UUID(roh) if roh else None


def _normalize_description(raw) -> str:
    """Zeilenenden vereinheitlichen, Rand-Whitespace weg. Der Rest bleibt wörtlich
    stehen — was der Nutzer tippt, geht so in `ram:Name` (BT-153) der CII-XML."""
    return str(raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _replace_items(db: Session, invoice: Invoice, raw_items) -> tuple[Decimal, Decimal]:
    """Positionen der Rechnung durch `raw_items` ersetzen (Position 1..n, lückenlos),
    liefert Netto- und Steuersumme.

    Bestehende Zeilen werden EINZELN über `db.delete()` entfernt, nie über ein
    Bulk-`query().delete()` — das umginge den `invoice_guard` (before_flush) und das
    Audit-Log still, genau wie das für `query().update()` dokumentierte Muster.
    Beim Anlegen ist die Schleife leer.
    """
    for alt in list(invoice.items):
        db.delete(alt)
    # Erst die Löschungen in die DB, dann die neuen Positionen — sonst könnten
    # gleiche `position`-Werte innerhalb eines Flushs kollidieren.
    db.flush()

    net_total = Decimal("0")
    tax_total = Decimal("0")
    for i, raw in enumerate(raw_items, 1):
        qty = Decimal(str(raw["quantity"]))
        price = Decimal(str(raw["unit_price"]))
        tax_rate = Decimal(str(raw["tax_rate"]))
        net, tax, gross = _calc_item(qty, price, tax_rate)
        db.add(InvoiceItem(
            invoice_id=invoice.id,
            position=i,
            description=_normalize_description(raw["description"]),
            unit=raw.get("unit", "Stück"),
            quantity=qty,
            unit_price=price,
            tax_rate=tax_rate,
            net_amount=net,
            tax_amount=tax,
            gross_amount=gross,
        ))
        net_total += net
        tax_total += tax
    return net_total, tax_total


def _apply_totals(invoice: Invoice, net_total: Decimal, tax_total: Decimal) -> None:
    invoice.net_total = net_total.quantize(Decimal("0.01"))
    invoice.tax_total = tax_total.quantize(Decimal("0.01"))
    invoice.gross_total = (net_total + tax_total).quantize(Decimal("0.01"))
    # GoBD: Aufbewahrungsfrist endet am 31.12. des (Ausstellungsjahr + 8), § 147 Abs. 4 AO.
    invoice.archive_until = berechne_archive_until(invoice.issue_date)


def _run_validation(db: Session, invoice: Invoice, company: Company) -> ValidationResult:
    """Regelprüfung (§ 14 UStG) + optionale Mustang-Prüfung der bereits erzeugten XML.

    Der Mustang-Zweig läuft nur mit `invoice.zugferd_xml`; ein Entwurf hat keine, dort
    ist das ein reiner In-Prozess-Regellauf ohne Subprocess. Legt das
    `ValidationResult` an, committet aber NICHT — das entscheidet der Aufrufer.
    """
    errors, warnings = validator.validate_invoice(invoice, company)

    mustang_result = None
    if invoice.zugferd_xml:
        fd, tmp_name = tempfile.mkstemp(suffix=".xml")
        xml_path = Path(tmp_name)
        try:
            os.write(fd, invoice.zugferd_xml.encode("utf-8"))
            os.close(fd)
            mustang_result = mustang.validate(xml_path)
        finally:
            xml_path.unlink(missing_ok=True)

    vr = ValidationResult(
        invoice_id=invoice.id,
        is_valid=len(errors) == 0 and (mustang_result is None or mustang_result["is_valid"]),
        errors=[{"code": e.code, "severity": e.severity, "message": e.message, "field": e.field} for e in errors],
        warnings=[{"code": w.code, "severity": w.severity, "message": w.message, "field": w.field} for w in warnings],
        mustang_output=mustang_result["raw"] if mustang_result else None,
    )
    db.add(vr)
    return vr


def _get_draft(db: Session, invoice_id: uuid.UUID) -> Invoice:
    """Entwurf laden oder mit sprechendem Fehler abbrechen.

    Die verbindliche Linie ist der `invoice_guard` auf Session-Ebene; diese Prüfung
    ist die freundliche Fehlermeldung davor.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Rechnung nicht gefunden")
    if invoice.status != "draft":
        raise HTTPException(
            400,
            "Nur Entwürfe können bearbeitet werden. Eine finalisierte Rechnung ist "
            "unveränderlich — Korrektur ausschließlich per Stornorechnung.",
        )
    # Eine Gutschrift ist der Spiegel ihres Originals, kein eigener Beleg (#8).
    # `build_storno` kopiert die Beträge 1:1; wären sie danach änderbar, entstünde
    # eine „Gutschrift zu RE-001" mit anderen Zahlen, und das ist buchhalterisch
    # keine Stornierung mehr, sondern eine Teilkorrektur. Die wäre ein eigener
    # Belegtyp (384) mit eigenem Weg, nicht ein aufgeweichtes Storno.
    #
    # Die Tür geht hier zu und nicht erst beim Finalisieren: wer erst zehn Minuten
    # Positionen ändert und dann abgewiesen wird, hat zehn Minuten verloren.
    if invoice.invoice_type == "credit_note":
        raise HTTPException(
            400,
            "Eine Gutschrift lässt sich nicht bearbeiten. Sie übernimmt die Beträge "
            "der Originalrechnung unverändert; anders wäre sie keine Stornierung "
            "mehr. Stimmt etwas nicht, verwirf diesen Entwurf und beginne neu.",
        )
    return invoice


def _items_as_json(invoice: Invoice) -> str:
    """Positionen für das Alpine-Formular. `normalize()` bei Menge und Steuersatz,
    damit `19.00` als `19` ankommt und zur Auswahlliste im Formular passt."""
    # `</` maskieren: die Liste steht im Template in einem <script>-Block, und eine
    # Beschreibung mit "</script>" würde ihn sonst vorzeitig schließen. `<\/` ist
    # gültiges JSON und dekodiert zum selben Zeichen.
    return json.dumps([
        {
            "description": item.description or "",
            "unit": item.unit,
            "quantity": str(item.quantity.normalize()),
            "unit_price": str(item.unit_price),
            "tax_rate": str(item.tax_rate.normalize()),
            "net_amount": float(item.net_amount),
            "tax_amount": float(item.tax_amount),
            "gross_amount": float(item.gross_amount),
        }
        for item in sorted(invoice.items, key=lambda i: i.position)
    ]).replace("</", "<\\/")


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
):
    # `outerjoin`, nicht `join`: die Verbindung dient nur der Suche nach dem
    # Kundennamen. Ein INNER JOIN wuerde jeden Entwurf ohne Kunden (#141) lautlos
    # aus der Liste werfen — Status 200, Seite vollstaendig, Rechnung unauffindbar.
    query = db.query(Invoice).outerjoin(Customer)
    if status:
        query = query.filter(Invoice.status == status)
    else:
        # Verworfene Entwürfe (#145) sind aus dem Weg geräumt — sie erscheinen nur
        # noch über den Statusfilter, nicht in der Alltagsliste.
        query = query.filter(Invoice.status != "discarded")
    if q:
        query = query.filter(Invoice.invoice_number.ilike(f"%{q}%") | Customer.name.ilike(f"%{q}%"))

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
        "seite": seite, "seiten": seiten, "gesamt": gesamt,
    })


@router.get("/neu", response_class=HTMLResponse)
def new_invoice_form(request: Request, db: Session = Depends(get_db)):
    customers = db.query(Customer).filter(Customer.deleted_at.is_(None), Customer.is_active == True).order_by(Customer.name).all()
    company = db.query(Company).filter(Company.id == 1).first()
    today = date.today()
    response = templates.TemplateResponse("invoices/form.html", {
        "request": request,
        "invoice": None,
        "customers": customers,
        "company": company,
        "today": today.isoformat(),
        "due_default": (today + timedelta(days=14)).isoformat(),
        "error": None,
    })
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
    company = _get_company(db)

    customer_id = _kunde_id(form)
    issue_date = date.fromisoformat(form.get("issue_date"))
    due_date = date.fromisoformat(form.get("due_date"))
    delivery_date, service_period_start, service_period_end = parse_leistungszeit_from_form(form)
    tax_category = form.get("tax_category", "S").strip() or "S"

    items_json = form.get("items_json", "[]")
    raw_items = json.loads(items_json)

    invoice_number = generate_next_invoice_number(db, issue_date=issue_date)

    invoice = Invoice(
        invoice_number=invoice_number,
        customer_id=customer_id,
        issue_date=issue_date,
        due_date=due_date,
        delivery_date=delivery_date,
        service_period_start=service_period_start,
        service_period_end=service_period_end,
        payment_terms=form.get("payment_terms", "").strip() or company.payment_terms_default,
        buyer_reference=form.get("buyer_reference", "").strip() or None,
        notes=form.get("notes", "").strip() or None,
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category=tax_category,
    )
    db.add(invoice)
    db.flush()

    net_total, tax_total = _replace_items(db, invoice, raw_items)
    _apply_totals(invoice, net_total, tax_total)

    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice.id}", status_code=303)


@router.get("/{invoice_id}/bearbeiten", response_class=HTMLResponse)
def edit_invoice_form(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    invoice = _get_draft(db, invoice_id)
    customers = db.query(Customer).filter(Customer.deleted_at.is_(None), Customer.is_active == True).order_by(Customer.name).all()
    company = db.query(Company).filter(Company.id == 1).first()
    return templates.TemplateResponse("invoices/form.html", {
        "request": request,
        "invoice": invoice,
        "items_json": _items_as_json(invoice),
        "customers": customers,
        "company": company,
        "today": date.today().isoformat(),
        "due_default": invoice.due_date.isoformat(),
        "error": None,
    })


@router.post("/{invoice_id}/bearbeiten")
async def update_invoice(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    invoice = _get_draft(db, invoice_id)
    company = _get_company(db)
    form = await request.form()

    delivery_date, service_period_start, service_period_end = parse_leistungszeit_from_form(form)

    # Unveränderlich bleiben `invoice_number`, `id`, `status` und `created_at` —
    # sie tauchen hier bewusst nicht auf.
    invoice.customer_id = _kunde_id(form)
    invoice.issue_date = date.fromisoformat(form.get("issue_date"))
    invoice.due_date = date.fromisoformat(form.get("due_date"))
    invoice.delivery_date = delivery_date
    invoice.service_period_start = service_period_start
    invoice.service_period_end = service_period_end
    invoice.tax_category = form.get("tax_category", "S").strip() or "S"
    invoice.payment_terms = form.get("payment_terms", "").strip() or company.payment_terms_default
    invoice.buyer_reference = form.get("buyer_reference", "").strip() or None
    invoice.notes = form.get("notes", "").strip() or None

    net_total, tax_total = _replace_items(db, invoice, json.loads(form.get("items_json", "[]")))
    _apply_totals(invoice, net_total, tax_total)

    # Nachprüfen mit den NEUEN Positionen: `_replace_items` hat sie erst in die Session
    # gelegt, die geladene `items`-Beziehung zeigt sonst noch den alten Stand.
    db.flush()
    db.expire(invoice, ["items"])
    _run_validation(db, invoice, company)

    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


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


@router.get("/{invoice_id}", response_class=HTMLResponse)
def invoice_detail(invoice_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Rechnung nicht gefunden")
    company = db.query(Company).filter(Company.id == 1).first()
    latest_validation = (
        db.query(ValidationResult)
        .filter(ValidationResult.invoice_id == invoice_id)
        .order_by(ValidationResult.validated_at.desc())
        .first()
    )
    cfg = datev_email._get_effective_smtp_config(db)
    # CC-Vorbelegung (#147) kommt allein aus der DB — kein .env-Gegenpart, deshalb
    # nicht über EffectiveSettings.
    app_config = db.query(AppConfig).filter(AppConfig.id == 1).first()
    cc_default, cc_herkunft = _cc_vorbelegung(invoice, app_config)
    return templates.TemplateResponse("invoices/detail.html", {
        "request": request,
        "invoice": invoice,
        "company": company,
        "validation": latest_validation,
        "datev_configured": bool(cfg.datev_bcc_email),
        "smtp_configured": bool(cfg.smtp_host),
        "cc_default": cc_default,
        "cc_herkunft": cc_herkunft,
        "protokoll": aenderungsprotokoll.protokoll_fuer(db, invoice_id),
    })


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
    company = _get_company(db)
    return templates.TemplateResponse("invoices/preview.html", {
        "request": request,
        "invoice": invoice,
        "company": company,
        # NUR ans Template — nicht an `invoice.zugferd_xml`. Die Vorschau erzeugt
        # keinen Beleg, sie zeigt nur, was beim Finalisieren entstünde.
        "xml": zugferd_xml.generate_xml(invoice, company),
    })


@router.get("/{invoice_id}/vorschau.pdf")
def preview_pdf(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    invoice = _get_draft_for_preview(db, invoice_id)
    company = _get_company(db)

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
        pdf_generator.generate_pdf(invoice, company, tmp_path, draft=True)
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
    company = _get_company(db)

    _run_validation(db, invoice, company)
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


def _arbeitswurzel() -> Path:
    """`storage/temp/` als Arbeitsplatz der Belegerzeugung.

    Bewusst NICHT das Temp-Verzeichnis des Betriebssystems: das Veröffentlichen
    unten ist ein `os.replace` und damit nur innerhalb desselben Dateisystems ein
    atomares Umbenennen. `storage` ist ein eigener Mount, über die Grenze hinweg
    scheitert es mit `Invalid cross-device link`.

    `temp/` ist aus der Archivansicht ausgenommen (`routers/archive.BEREICHE` kennt
    nur `pdfs` und `xml`) und war dort schon vorher als Platz für Zwischendateien
    beschrieben.
    """
    wurzel = settings.storage_path / "temp"
    wurzel.mkdir(parents=True, exist_ok=True)
    return wurzel


def _veroeffentliche(pdf_quelle: Path, xml_quelle: Path) -> list[Path]:
    """Fertigen Beleg aus dem Arbeitsverzeichnis ins Archiv übernehmen.

    `os.replace` statt Kopieren: innerhalb desselben Dateisystems ist das ein
    atomares Umbenennen. Im Archiv erscheint deshalb nie eine halb geschriebene
    Datei, und die Archivansicht, die das Verzeichnis ungefiltert vorliest, sieht
    entweder nichts oder den vollständigen Beleg.

    Bricht der zweite Zug ab, wird der erste zurückgenommen. Ein PDF ohne seine XML
    im Archiv wäre eine E-Rechnung, der genau der Teil fehlt, der seit 2025 den
    Vorrang hat.
    """
    ziele = [
        (pdf_quelle, settings.storage_path / "pdfs" / pdf_quelle.name),
        (xml_quelle, settings.storage_path / "xml" / xml_quelle.name),
    ]
    fertig: list[Path] = []
    try:
        for quelle, ziel in ziele:
            ziel.parent.mkdir(parents=True, exist_ok=True)
            os.replace(quelle, ziel)
            fertig.append(ziel)
    except OSError:
        for ziel in fertig:
            ziel.unlink(missing_ok=True)
        raise
    return fertig


@router.post("/{invoice_id}/finalisieren")
def finalize_invoice(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    # Zeilensperre vor der ersten teuren Zeile (#6). Zwei gleichzeitige Anfragen lasen
    # denselben Entwurf, sahen beide `draft` und starteten beide Ghostscript und
    # Mustang für denselben Beleg; am Ende veröffentlichte der zweite Lauf über den
    # fertigen Beleg des ersten hinweg. `FOR UPDATE` hält den zweiten hier fest, bis
    # der erste committet hat, und die Statusprüfung darunter liest dann den neuen
    # Stand: kein Entwurf mehr, also eine saubere Absage statt einer zweiten Pipeline.
    #
    # Die Sperre steht bis zum Commit am Ende dieser Funktion, deckt also die gesamte
    # Belegerzeugung ab. Das Warten ist gewollt: die Alternative wäre `NOWAIT` und
    # damit eine Fehlermeldung an einen Nutzer, der nur zweimal geklickt hat.
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id)
        .with_for_update()
        .first()
    )
    if not invoice:
        raise HTTPException(404)
    if invoice.status != "draft":
        raise HTTPException(400, "Nur Entwürfe können finalisiert werden.")

    company = _get_company(db)

    # Validierungs-Gate (§ 14 UStG): eine Rechnung mit harten Fehlern (z. B. keine
    # Positionen, falsche Summen) darf NICHT finalisiert und archiviert werden —
    # sonst wanderte ein rechtswidriger Beleg unveränderlich ins GoBD-Archiv.
    errors, _ = validator.validate_invoice(invoice, company)
    if errors:
        raise HTTPException(
            400,
            "Rechnung ist nicht rechtskonform und kann nicht finalisiert werden: "
            + "; ".join(e.message for e in errors),
        )

    # 1. ZUGFeRD XML erzeugen
    xml_content = zugferd_xml.generate_xml(invoice, company)
    invoice.zugferd_xml = xml_content

    # Die gesamte Belegerzeugung läuft in einem Wegwerf-Verzeichnis, NICHT im Archiv
    # (#12, #13, Dateiteil von #6). `storage/pdfs/` und `storage/xml/` sind zugleich
    # das GoBD-Archiv und das, was `routers/archive.py` ungefiltert aus dem
    # Dateisystem vorliest; was dort liegt, ist für den Betrachter ein Beleg. Solange
    # die Zwischenstufen dort entstanden, war jede halbfertige Stufe sekundenlang
    # sichtbar und herunterladbar, und ein gescheiterter Commit ließ ein PDF mit
    # echter Rechnungsnummer zurück, das die Datenbank nicht kannte.
    arbeitsverzeichnis = Path(tempfile.mkdtemp(
        prefix=f"finalisieren-{invoice.invoice_number}-", dir=_arbeitswurzel()))
    try:
        # 2. Visuelles PDF erzeugen
        visual_pdf = arbeitsverzeichnis / f"{invoice.invoice_number}_visual.pdf"
        pdf_generator.generate_pdf(invoice, company, visual_pdf)

        # 3. Mustang: XML in PDF einbetten → ZUGFeRD PDF
        xml_path = arbeitsverzeichnis / f"{invoice.invoice_number}.xml"
        xml_path.write_text(xml_content, encoding="utf-8")

        # Pipeline: visuelles PDF → PDF/A-3 (Ghostscript) → Mustang bettet XML ein.
        # FAIL-CLOSED (#98 P0.1): eine E-Rechnung OHNE eingebettete ZUGFeRD-XML ist seit
        # 2025 rechtlich unvollständig (der XML-Teil hat Vorrang). Gelingt die Einbettung
        # nicht, wird NICHT als reines Visual-PDF „issued" — die Rechnung bleibt draft.
        # Es geht nichts verloren: kein Commit, und das Arbeitsverzeichnis fällt im
        # `finally` samt allen Zwischenstufen weg (die Datenverlust-Regression
        # 2026-07-08 betraf das Löschen eines bereits finalisierten PDFs — hier wird
        # gar nichts finalisiert).
        zugferd_pdf = arbeitsverzeichnis / f"{invoice.invoice_number}.pdf"
        combined = False
        pruefgrund = ""      # erster Prüffehler, wandert in die Fehlermeldung (s. u.)
        if pdfa.gs_available() and mustang.jar_available():
            pdfa_pdf = arbeitsverzeichnis / f"{invoice.invoice_number}_pdfa.pdf"
            if pdfa.to_pdfa3(visual_pdf, pdfa_pdf, title=invoice.invoice_number) and \
                    mustang.combine(pdfa_pdf, xml_path, zugferd_pdf):
                # E1 (#98 Hardness): `combine` liefert True (rc=0 + Datei existiert) auch
                # für ein PDF, das ein Empfänger-/Prüfer-System ablehnen würde. Mustang
                # ist die Wahrheit — nur ein Ergebnis mit is_valid UND XML:valid (PDF/A +
                # Schema + Schematron griffen) gilt als gültige E-Rechnung. Sonst
                # fail-closed: die Rechnung bleibt draft (unten), kein Commit.
                result = mustang.validate(zugferd_pdf)
                if result["is_valid"] and "XML:valid" in result["raw"]:
                    combined = True
                else:
                    fehler = result.get("errors") or []
                    pruefgrund = str(fehler[0]).strip() if fehler else ""

        if not combined:
            db.rollback()
            # Der Prüfbericht gehört in die Meldung: ohne ihn bleibt dem Menschen nur
            # „nochmal versuchen", und der zweite Versuch scheitert an derselben Regel
            # (Abnahme 2026-08-09: BR-CO-26, fehlende Verkäufer-Kennung — nicht erratbar).
            # Auf 400 Zeichen gekürzt, Mustang hängt ganze Schematron-Pfade an.
            grund = f" Grund der Prüfung: {pruefgrund[:400]}" if pruefgrund else ""
            raise HTTPException(
                400,
                "E-Rechnung konnte nicht erzeugt werden: die ZUGFeRD-XML ließ sich nicht "
                "ins PDF einbetten (PDF/A- oder Mustang-Schritt fehlgeschlagen). Die "
                f"Rechnung bleibt Entwurf — bitte erneut finalisieren.{grund}",
            )

        invoice.pdf_filename = zugferd_pdf.name
        invoice.status = "issued"

        # Erst ins Archiv, dann committen. Die umgekehrte Reihenfolge wäre der
        # schlechtere Fehler: eine gestellte Rechnung ohne Beleg auf der Platte ist
        # unveränderlich und damit nicht mehr reparierbar, während ein Beleg ohne
        # Datenbankzeile sich durch erneutes Finalisieren auflöst. Scheitert der
        # Commit, wird das eben Veröffentlichte wieder eingesammelt.
        veroeffentlicht = _veroeffentliche(zugferd_pdf, xml_path)
        try:
            db.commit()
        except Exception:
            for ziel in veroeffentlicht:
                ziel.unlink(missing_ok=True)
            db.rollback()
            raise
    finally:
        shutil.rmtree(arbeitsverzeichnis, ignore_errors=True)

    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/datev-senden")
def send_to_datev(invoice_id: uuid.UUID, customer_email: str = Form(""),
                  cc_email: str = Form(""), db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404)
    if invoice.status not in ("issued", "paid"):
        raise HTTPException(400, "Nur finalisierte Rechnungen können gesendet werden.")
    if not invoice.pdf_filename:
        raise HTTPException(400, "Kein PDF vorhanden. Bitte zuerst finalisieren.")
    # Fail-closed (#98 P0.1): nur ein ZUGFeRD-PDF (mit eingebetteter XML) darf raus.
    # Ein reines Visual-PDF (*_visual.pdf) ist keine gültige E-Rechnung.
    if invoice.pdf_filename.endswith("_visual.pdf"):
        raise HTTPException(
            400,
            "PDF ohne eingebettete E-Rechnung (Visual-PDF) darf nicht versendet "
            "werden. Rechnung erneut finalisieren, um ein ZUGFeRD-PDF zu erzeugen.",
        )

    pdf_path = settings.storage_path / "pdfs" / invoice.pdf_filename
    to_email = customer_email or (invoice.customer.email if invoice.customer else "")
    if not to_email:
        raise HTTPException(400, "Keine E-Mail-Adresse des Kunden bekannt.")

    # E3 (#98 Hardness): der Dateiname (`_visual`-Suffix) ist nur eine Vorabprüfung
    # und beweist nichts über den Inhalt — ein bares ReportLab-PDF ohne eingebettete
    # ZUGFeRD-XML hätte den Suffix-Check passiert. Verbindlich ist Mustang: nur ein
    # PDF mit gültig eingebetteter XML (XML:valid) darf raus. Ohne Mustang lässt sich
    # die Einbettung nicht beweisen → nicht senden (fail-closed).
    if not mustang.jar_available():
        raise HTTPException(
            400, "E-Rechnungs-Validierung nicht möglich (Mustang nicht verfügbar) — "
            "Versand abgebrochen.")
    validation = mustang.validate(pdf_path)
    if not (validation["is_valid"] and "XML:valid" in validation["raw"]):
        raise HTTPException(
            400, "PDF enthält keine gültig eingebettete E-Rechnung (Mustang-"
            "Validierung fehlgeschlagen). Bitte die Rechnung erneut finalisieren.")

    # Ab hier findet ein echter Zustellversuch statt — erst ab hier wird
    # protokolliert (#146). Ein an den Vorprüfungen gescheiterter Aufruf hat nie
    # gesendet und gehört nicht ins Versandprotokoll.
    #
    # Der Versuch wird geschrieben und committet, BEVOR SMTP angesprochen wird (#10).
    # Vorher lief es andersherum, und ein Commit-Fehler nach erfolgreichem Versand
    # hinterliess keine Spur: die Mail war beim Kunden und beim Steuerbuero, die
    # Datenbank sagte „nie gesendet", und der naechste Klick schickte den Beleg ein
    # zweites Mal. Der Ausgang ist zu diesem Zeitpunkt offen (`success = None`) und
    # wird unten nachgetragen; bleibt er offen stehen, ist genau das die Auskunft:
    # die Mail koennte drausssen sein, bitte im Postausgang nachsehen.
    # Vor `db.add(protokoll)` (#58): eine abgelehnte Eingabe hat nie gesendet und
    # darf keine Protokollzeile mit offenem Ausgang hinterlassen, die spaeter wie
    # ein moeglicher Zweitversand aussieht.
    cc_fehler = empfaenger.pruefe(cc_email)
    if cc_fehler:
        raise HTTPException(400, cc_fehler)
    # `ohne=to_email`: wer im An-Feld steht, bekaeme die Rechnung sonst zweimal.
    cc = empfaenger.normalisiere(cc_email, ohne=to_email)
    protokoll = InvoiceSendLog(invoice_id=invoice.id, to_email=to_email,
                               cc_email=cc or None, datev_bcc=True, success=None)
    db.add(protokoll)
    db.commit()
    try:
        datev_email.send_invoice(
            to_email=to_email,
            invoice_number=invoice.invoice_number,
            customer_name=invoice.customer.name,
            pdf_path=pdf_path,
            bcc_datev=True,
            db=db,
            cc_email=cc,
        )
    except datev_email.EmailError as e:
        protokoll.success = False
        protokoll.error = str(e)
        db.commit()
        raise HTTPException(400, str(e))

    protokoll.success = True
    # `datev_sent_at` ist der ERSTversand und bleibt unverfälscht: der invoice_guard
    # verbietet Umdatieren (#98 P0.3), ein bedingungsloses Setzen ließ deshalb jeden
    # Zweitversand nach dem Absenden der Mail am Commit scheitern. Die weiteren
    # Versuche stehen im Protokoll.
    if invoice.datev_sent_at is None:
        invoice.datev_sent_at = datetime.now(timezone.utc)
    db.commit()

    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.get("/{invoice_id}/pdf")
def download_pdf(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice or not invoice.pdf_filename:
        raise HTTPException(404, "PDF nicht gefunden")
    pdf_path = settings.storage_path / "pdfs" / invoice.pdf_filename
    if not pdf_path.exists():
        raise HTTPException(404, "PDF-Datei nicht auf dem Server gefunden")
    return FileResponse(str(pdf_path), media_type="application/pdf", filename=invoice.pdf_filename)


_VALID_TRANSITIONS: dict[str, set[str]] = {
    "paid": {"issued"},
    "cancelled": {"issued"},
}


@router.post("/{invoice_id}/status")
def update_status(invoice_id: uuid.UUID, new_status: str = Form(...), db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404)
    if new_status not in _VALID_TRANSITIONS:
        raise HTTPException(400, f"Ungültiger Zielstatus '{new_status}'.")
    if invoice.status not in _VALID_TRANSITIONS[new_status]:
        raise HTTPException(
            400,
            f"Übergang von '{invoice.status}' nach '{new_status}' ist nicht erlaubt."
        )

    # Bezahlt trotz Gutschrift (#15). Ein Original, zu dem eine Gutschrift
    # existiert, darf nicht als bezahlt gelten: das wäre ein Zahlungsstatus, der
    # seiner eigenen Korrektur widerspricht, und in OPOS und DATEV zwei Buchungen,
    # die sich gegenseitig ausschließen. Auch der noch offene Entwurf sperrt, denn
    # er ist die erklärte Absicht zu korrigieren.
    #
    # Gesperrt wird der Weg nach `paid`; das Original wird NICHT automatisch auf
    # `cancelled` gesetzt. `invoice_guard.ALLOWED_TRANSITIONS` macht `paid` zum
    # Endzustand, `paid → cancelled` ist verboten, und stornieren darf man hier
    # ausdrücklich auch eine bereits bezahlte Rechnung. Eine Automatik griffe damit
    # in der Hälfte der Fälle stillschweigend nicht. Den Wächter dafür
    # aufzuweichen wäre der falsche Tausch: die Statusmaschine ist eine GoBD-Zusage,
    # keine Ergonomiefrage. Der Weg nach `cancelled` bleibt eine bewusste
    # menschliche Entscheidung und wird hier bewusst nicht mitgesperrt.
    if new_status == "paid":
        gutschrift = (
            db.query(Invoice)
            .filter(Invoice.original_invoice_id == invoice.id,
                    Invoice.status != "discarded")
            .order_by(Invoice.invoice_number)
            .first()
        )
        if gutschrift:
            raise HTTPException(
                400,
                f"Zu dieser Rechnung existiert die Gutschrift "
                f"{gutschrift.invoice_number}. Ein stornierter Beleg kann nicht als "
                "bezahlt geführt werden. Setze ihn auf „storniert“, oder verwirf "
                "die Gutschrift, falls sie versehentlich entstanden ist.",
            )

    invoice.status = new_status
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/verwerfen")
def discard_draft(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    """Entwurf verwerfen (#145) — Status statt Hard-Delete.

    Verbindlich ist der `invoice_guard` (Session-Ebene); die Prüfung hier ist die
    freundliche Antwort (400 statt 500), nicht die Absicherung. Die Rechnungsnummer
    bleibt belegt: sie ist beim Anlegen des Entwurfs vergeben worden, und der
    verbliebene Datensatz ist das Einzige, was die Nummernlücke später erklärt.
    """
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Rechnung nicht gefunden")
    if invoice.status != "draft":
        raise HTTPException(
            400, "Nur Entwürfe können verworfen werden. Eine gestellte Rechnung "
            "bleibt erhalten — Korrektur nur per Storno.")
    invoice.status = "discarded"
    db.commit()
    return RedirectResponse(url="/invoices", status_code=303)


@router.post("/{invoice_id}/zurueckholen")
def restore_draft(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    invoice = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(404, "Rechnung nicht gefunden")
    if invoice.status != "discarded":
        raise HTTPException(400, "Nur verworfene Entwürfe können zurückgeholt werden.")
    invoice.status = "draft"
    db.commit()
    return RedirectResponse(url=f"/invoices/{invoice_id}", status_code=303)


@router.post("/{invoice_id}/storno")
def create_storno(invoice_id: uuid.UUID, db: Session = Depends(get_db)):
    original = db.query(Invoice).filter(Invoice.id == invoice_id).first()
    if not original:
        raise HTTPException(404, "Rechnung nicht gefunden")
    if original.status not in ("issued", "paid"):
        raise HTTPException(400, "Nur finalisierte Rechnungen (issued/paid) können storniert werden.")
    if original.invoice_type == "credit_note":
        raise HTTPException(400, "Eine Stornorechnung kann nicht erneut storniert werden.")

    # Pro Original höchstens EINE Gutschrift (#7). Zwei Gutschriften zum selben
    # Beleg mindern die Forderung doppelt: in der OPOS-Liste, in der DATEV-Buchung
    # und in der Umsatzsteuervoranmeldung.
    #
    # Auch ein noch OFFENER Entwurf blockiert. Sonst entstünden zwei Entwürfe, die
    # beide finalisierbar sind, und der Fehler fiele erst beim zweiten
    # Finalisieren auf, wenn bereits ein Beleg unveränderlich im Archiv liegt.
    #
    # Ein VERWORFENER Storno blockiert nicht: wer versehentlich storniert und den
    # Entwurf verwirft, muss den Beleg erneut stornieren können, sonst wäre ein
    # Fehlgriff endgültig.
    #
    # Die Prüfung steht VOR `generate_next_invoice_number`: der Zähler auf
    # `Company` wird beim Ziehen der Nummer erhöht, eine Ablehnung danach ließe
    # eine Nummernlücke ohne jeden Datensatz zurück — genau die Lücke, die #145
    # mit dem Status `discarded` vermeiden wollte.
    vorhandene = (
        db.query(Invoice)
        .filter(Invoice.original_invoice_id == original.id,
                Invoice.status != "discarded")
        .order_by(Invoice.invoice_number)
        .first()
    )
    if vorhandene:
        raise HTTPException(
            400,
            f"Zu dieser Rechnung existiert bereits die Gutschrift "
            f"{vorhandene.invoice_number}. Ein Beleg wird nur einmal storniert; "
            "eine zweite Gutschrift würde die Forderung doppelt mindern. Ist die "
            "vorhandene Gutschrift versehentlich entstanden, verwirf zuerst ihren "
            "Entwurf.",
        )

    _get_company(db)  # stellt sicher, dass Firmendaten konfiguriert sind (sonst 400)
    number = generate_next_invoice_number(db)
    from app.services.storno import build_storno
    storno = build_storno(original, number, date.today())
    db.add(storno)
    db.commit()
    return RedirectResponse(url=f"/invoices/{storno.id}", status_code=303)
