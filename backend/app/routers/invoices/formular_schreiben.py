import json
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.routers.invoices.formular_lesen import (
    abzug_aus_form,
    belegsprache_aus_form,
    faelligkeit_aus_form,
    kunde_id,
    positionen_aus_formular,
    pruefe_einheiten,
    pruefe_positionsangaben,
    vorbelegung_aus,
    zahlungsbedingungen,
)
from app.routers.invoices.formular_herleitung import pruefe_herleitung_belegart
from app.services import kundenvorgaben
from app.services.archive_frist import berechne_archive_until
from app.services.belegart import InvoiceTypeNotSelectable, ist_storno, manuelle_belegart
from app.services.belegsprache import darstellung
from app.services.belegsprache.zahlungshinweis import zahlungstext_beim_speichern
from app.services.belegsummen import Belegsummen, belegsummen
from app.services.ersatzrechnung import ErsatzNichtMoeglich, pruefe_ersetzbar
from app.services.kunde_zuordenbar import (
    Zuordnung,
    kennung_aufloesen,
    meldung_fuer,
    zuordenbare_kunden,
)
from app.services.leistungszeit import parse_leistungszeit_from_form


def entwurf_laden(db: Session, invoice_id: uuid.UUID) -> Invoice:
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
    if ist_storno(invoice.invoice_type):
        raise HTTPException(
            400,
            "Eine Stornorechnung lässt sich nicht bearbeiten. Sie übernimmt die Beträge "
            "der Originalrechnung unverändert; anders wäre sie keine Stornierung "
            "mehr. Stimmt etwas nicht, verwirf diesen Entwurf und beginne neu.",
        )
    return invoice


def positionen_ersetzen(db: Session, invoice: Invoice, positionen: list[InvoiceItem]) -> None:
    """Positionen der Rechnung durch `positionen` ersetzen.

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

    for item in positionen:
        item.invoice_id = invoice.id
        db.add(item)


def summen_schreiben(
    invoice: Invoice, summen: Belegsummen,
    abzug_betrag: Decimal | None, abzug_grund: str | None,
) -> None:
    """Summen aus belegsummen schreiben; net_total ist die Steuerbasis (#147):
    mit Abzug enthält sie die Minderung, damit Kleinbetragsgrenze, Zahlungs-QR
    und Kennzahlen ohne Sonderfall stimmen."""
    invoice.net_total = summen.steuerbasis
    invoice.tax_total = summen.steuer
    invoice.gross_total = summen.brutto
    invoice.abzug_betrag = abzug_betrag
    invoice.abzug_grund = abzug_grund
    # GoBD: Aufbewahrungsfrist endet am 31.12. des (Ausstellungsjahr + 8), § 147 Abs. 4 AO.
    invoice.archive_until = berechne_archive_until(invoice.issue_date)


def waehlbare_kunden(db: Session) -> list[Customer]:
    """Kunden, die das Formular zur Auswahl anbietet (nicht gelöscht, aktiv)."""
    return zuordenbare_kunden(db)


def kunde_zuordnung_pruefen(db: Session, customer_id) -> None:
    """Hand-gesendete kunde_id: nur zuordenbare Kunden, sonst fachliche Absage."""
    if customer_id is None:
        return
    lage, _kunde = kennung_aufloesen(db, customer_id)
    if lage is not Zuordnung.ZUORDENBAR:
        raise HTTPException(400, meldung_fuer(lage))


def leerer_formularzustand() -> SimpleNamespace:
    """Veränderlicher Zustand des Neuanlage-Formulars (Vorlage/Ersatz füllen ihn)."""
    return SimpleNamespace(
        vorbelegung=None, items_json=None, error=None,
        kunde_hinweis=None, ersetzt_beleg=None,
    )


def vorlage_anwenden(db: Session, vorlage: str, customers, zustand: SimpleNamespace) -> None:
    """Kopieren (docs/specs/kopieren.md): Vorbelegung aus der Vorlagenrechnung."""
    try:
        vorlage_id = uuid.UUID(vorlage)
    except ValueError:
        zustand.error = "Vorlage ungueltig"
        return
    quelle = (
        db.query(Invoice)
        .options(joinedload(Invoice.items))
        .filter(Invoice.id == vorlage_id)
        .first()
    )
    if quelle is None:
        zustand.error = "Vorlage nicht gefunden"
        return
    zustand.vorbelegung, zustand.items_json, zustand.kunde_hinweis = vorbelegung_aus(quelle, customers)


def ersatz_anwenden(db: Session, ersetzt: str, customers, zustand: SimpleNamespace) -> None:
    """Ersatzrechnung: Vorbelegung wie beim Kopieren, dazu Abzug und Belegart des Originals."""
    try:
        zustand.ersetzt_beleg = pruefe_ersetzbar(db, ersetzt)
    except ErsatzNichtMoeglich as fehler:
        zustand.error = str(fehler)
        return
    zustand.vorbelegung, zustand.items_json, zustand.kunde_hinweis = vorbelegung_aus(
        zustand.ersetzt_beleg, customers, mit_abzug=True)
    zustand.vorbelegung.invoice_type = zustand.ersetzt_beleg.invoice_type


def belegart_neuanlage(form) -> str:
    """Belegart vor Feldregeln und Nummernvergabe."""
    # Belegart vor Feldregeln und Nummernvergabe (Spec: Reihenfolge beim
    # Schreiben). Eine abgelehnte Wahl darf weder Zaehler noch Zeile anfassen.
    # Fehlendes Feld = Standard (abwaertskompatibel); die Waehlbarkeitspruefung
    # ist eigener Schritt, nicht Mitgliedschaft in der Typtabelle (381/384
    # waeren sonst waehlbar).
    try:
        return manuelle_belegart(form.get("invoice_type"))
    except InvoiceTypeNotSelectable as fehler:
        raise HTTPException(400, str(fehler)) from fehler


def sprache_und_zahlungsbedingungen(db: Session, form, company: Company, customer_id,
                                    leistungszeit) -> tuple[str, object, str]:
    """Belegsprache, Kundenvorgabe und Zahlungsbedingungen der Neuanlage."""
    _, service_period_start, service_period_end = leistungszeit
    # Sprache vor Nummernvergabe: ungueltiger Wert und fehlende englische
    # Vorgabe duerfen den Zaehler nicht erhoehen (docs/specs/belegsprache.md S1/S7).
    # Kundenvorgabe (falls gesetzt) ueberschreibt die Formularwahl: beim Anlegen
    # weiss der Nutzer den Kundenwunsch oft nicht, im Entwurf bleibt es aenderbar.
    document_language = belegsprache_aus_form(form)
    kunde = (
        db.query(Customer).filter(Customer.id == customer_id).first()
        if customer_id is not None else None
    )
    # Vorbelegung aus dem Kundenstamm (Festlegung 15): Kopf-/Fusstext mit
    # ersetztem {leistungsmonat}, Zahlungshinweis, Belegsprache. Formularwerte
    # gewinnen; leer heisst, der Kunde darf seine Vorgabe beitragen.
    vorgabe = kundenvorgaben.entwurfs_vorbelegung(
        kunde, service_period_start, service_period_end,
    )
    if vorgabe.belegsprache:
        document_language = vorgabe.belegsprache
    payment_terms = zahlungsbedingungen(
        form, company, document_language, kunden_hinweis=vorgabe.zahlungshinweis,
    )
    return document_language, vorgabe, payment_terms


def zahlungsfrist_pruefen(due_date: date | None, payment_terms: str | None) -> None:
    """BR-CO-25: Fälligkeit (BT-9) ODER Zahlungsbedingungen (BT-20)."""
    # Vor Nummernvergabe: BR-CO-25 verlangt bei offenem Betrag Fälligkeit (BT-9)
    # ODER Zahlungsbedingungen (BT-20). Der Validator meldet dasselbe als
    # DUE_DATE_OR_PAYMENT_TERMS_REQUIRED; hier stoppt es die Eingabe als
    # Formularfehler, bevor die DB-CHECK (Migration 026) den Commit kippt und
    # der Zaehler durch eine abgewiesene Eingabe steigt.
    if due_date is None and not (payment_terms or "").strip():
        raise HTTPException(400, FRIST_ODER_BEDINGUNGEN_FEHLT)


FRIST_ODER_BEDINGUNGEN_FEHLT = (
    "DUE_DATE_OR_PAYMENT_TERMS_REQUIRED: Ohne Fälligkeitsdatum braucht der "
    "Beleg Zahlungsbedingungen (EN 16931 BR-CO-25). Bitte eines von "
    "beiden angeben."
)


def kopfdaten_lesen(db: Session, form, company: Company) -> dict:
    """Kopffelder der Neuanlage als Invoice-Argumente; alle Prüfungen vor der Nummernvergabe."""
    customer_id = kunde_id(form)
    kunde_zuordnung_pruefen(db, customer_id)
    issue_date = date.fromisoformat(form.get("issue_date"))
    due_date = faelligkeit_aus_form(form)
    leistungszeit = parse_leistungszeit_from_form(form)
    delivery_date, service_period_start, service_period_end = leistungszeit
    tax_category = form.get("tax_category", "S").strip() or "S"
    invoice_type = belegart_neuanlage(form)
    pruefe_herleitung_belegart(json.loads(form.get("items_json", "[]")), invoice_type)
    document_language, vorgabe, payment_terms = sprache_und_zahlungsbedingungen(
        db, form, company, customer_id, leistungszeit)
    kunde = (
        db.query(Customer).filter(Customer.id == customer_id).first()
        if customer_id is not None else None
    )
    payment_terms = zahlungstext_beim_speichern(
        invoice_type, payment_terms, company,
        due_date=due_date, issue_date=issue_date, customer=kunde,
        darstellung=darstellung(document_language),
    )
    zahlungsfrist_pruefen(due_date, payment_terms)
    return dict(
        customer_id=customer_id,
        issue_date=issue_date,
        due_date=due_date,
        delivery_date=delivery_date,
        service_period_start=service_period_start,
        service_period_end=service_period_end,
        payment_terms=payment_terms,
        buyer_reference=form.get("buyer_reference", "").strip() or None,
        buyer_order_reference=form.get("buyer_order_reference", "").strip() or None,
        notes=form.get("notes", "").strip() or None,
        # Kopf-/Fusstext: Formularfeld gewinnt, sonst Vorbelegung aus dem
        # Kundenstamm (nur leere Felder werden gefuellt, siehe oben).
        kopftext=(form.get("kopftext", "").strip() or vorgabe.kopftext) or None,
        fusstext=(form.get("fusstext", "").strip() or vorgabe.fusstext) or None,
        tax_category=tax_category,
        invoice_type=invoice_type,
        document_language=document_language,
    )


def positionen_und_summen_pruefen(form) -> tuple[list[InvoiceItem], Belegsummen, Decimal | None, str | None]:
    """Positionen, Abzug und Summen der Neuanlage prüfen, vor der Nummernvergabe."""
    items_json = form.get("items_json", "[]")
    raw_items = json.loads(items_json)
    # Vor Nummernvergabe: unbekannte Einheit darf weder Zaehler noch Zeile anfassen.
    pruefe_einheiten(raw_items)
    pruefe_positionsangaben(raw_items)

    # Abzug und Summen vor Nummernvergabe pruefen: ein ValueError aus belegsummen
    # (Abzug zu hoch, nicht positiv, uneindeutiger Steuersatz, ohne Positionen)
    # darf den Zaehler genauso wenig erhoehen wie eine unvollstaendige Eingabe.
    abzug_betrag, abzug_grund = abzug_aus_form(form)
    positionen = positionen_aus_formular(raw_items)
    try:
        summen = belegsummen(positionen, abzug_betrag)
    except ValueError as fehler:
        raise HTTPException(400, str(fehler)) from None
    return positionen, summen, abzug_betrag, abzug_grund


def ersetzt_id_pruefen(db: Session, form) -> uuid.UUID | None:
    """Ersatzbezug der Neuanlage; eine abgelehnte Ersatzrechnung verbraucht keine Nummer."""
    # Vor Nummernvergabe: eine abgelehnte Ersatzrechnung darf weder Zaehler noch
    # Zeile anfassen (docs/specs/ersatzrechnung.md).
    ersetzt_id = None
    if form.get("ersetzt_invoice_id"):
        try:
            ersetzt_id = pruefe_ersetzbar(db, form.get("ersetzt_invoice_id")).id
        except ErsatzNichtMoeglich as fehler:
            raise HTTPException(400, str(fehler)) from fehler
    return ersetzt_id
