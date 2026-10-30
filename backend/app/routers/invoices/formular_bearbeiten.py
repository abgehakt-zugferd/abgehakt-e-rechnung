import json
from datetime import date
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.routers.invoices.formular_herleitung import pruefe_herleitung_belegart
from app.routers.invoices.formular_lesen import (
    abzug_aus_form,
    belegart_waehlbar,
    belegsprache_aus_form,
    faelligkeit_aus_form,
    kunde_id,
    positionen_aus_formular,
    pruefe_einheiten,
    pruefe_positionsangaben,
)
from app.routers.invoices.zahlungsbedingungen import zahlungsbedingungen
from app.routers.invoices.formular_schreiben import (
    FRIST_ODER_BEDINGUNGEN_FEHLT,
    kunde_zuordnung_pruefen,
    zahlungsfrist_pruefen,
)
from app.services import belegsperre, kundenvorgaben
from app.services.auftragszahlung import ist_rechnungsauftrag
from app.services.belegart import InvoiceTypeNotSelectable, manuelle_belegart
from app.services.belegsprache import darstellung
from app.services.belegsprache.zahlungshinweis import zahlungstext_beim_speichern
from app.services.belegsprache.zahlungsvorgabe import ist_vorgabe_der_anderen_sprache
from app.services.belegsummen import Belegsummen, belegsummen


class FormularFehler(Exception):
    """Abgelehnte Eingabe beim Bearbeiten: das Formular erscheint noch einmal mit `meldung`."""

    def __init__(self, meldung):
        super().__init__(meldung)
        self.meldung = meldung


def ersatzbezug_sperren(form) -> None:
    # Der Ersatzbezug entsteht nur beim Anlegen (docs/specs/ersatzrechnung.md). Das
    # Bearbeitungsformular traegt kein solches Feld; ein mitgesendetes ist manipuliert.
    if form.get("ersetzt_invoice_id") is not None:
        raise FormularFehler(
            "ERSATZ_BEZUG_UNVERAENDERLICH: Der Bezug einer Ersatzrechnung wird beim "
            "Anlegen gesetzt und danach nicht mehr geaendert.",
        )


def belegart_aendern(invoice: Invoice, form) -> None:
    # Belegart: vor jeder Feld- oder Positionsaenderung entscheiden (Spec:
    # Reihenfolge beim Schreiben). Ein normaler Entwurf darf zwischen den manuellen Arten
    # wechseln. Ein Systembeleg oder importierter 389 behaelt seine Art:
    # fehlendes Feld heisst "unveraendert", ein mitgesendetes Feld wird
    # abgelehnt, nicht ignoriert — das Formular bietet dort kein Typfeld, also
    # ist ein mitgesendeter Wert immer ein manipulierter POST.
    typ_manuell_waehlbar = belegart_waehlbar(invoice)
    roh_typ = form.get("invoice_type")
    if roh_typ is not None and not typ_manuell_waehlbar:
        raise FormularFehler(
            "INVOICE_TYPE_NOT_SELECTABLE: Die Belegart dieses Entwurfs "
            f"({invoice.invoice_type}) steht nicht zur manuellen Wahl; "
            "sie entsteht auf ihrem eigenen Weg und bleibt unveraendert.",
        )
    try:
        ziel_typ = invoice.invoice_type if roh_typ is None else manuelle_belegart(roh_typ)
        if not belegsperre.gilt(invoice):
            pruefe_herleitung_belegart(
                json.loads(form.get("items_json", "[]")), ziel_typ, bestand=invoice,
            )
        invoice.invoice_type = ziel_typ
    except InvoiceTypeNotSelectable as fehler:
        raise FormularFehler(str(fehler)) from fehler
    except HTTPException as fehler:
        raise FormularFehler(fehler.detail) from fehler


def beleg_binden(
    db: Session, invoice: Invoice, form, service_period_start, service_period_end,
) -> tuple[list, bool, object]:
    """Positionen und Kunde übernehmen; Beleg-Herkunft bindet sie an den Bestand.

    Rückgabe: (rohe Positionen, aus_beleg, Kunde vor dem Speichern).
    """
    # Unveränderlich bleiben `invoice_number`, `id`, `status` und `created_at` —
    # sie tauchen hier bewusst nicht auf.
    rohe_positionen = json.loads(form.get("items_json", "[]"))
    aus_beleg = belegsperre.gilt(invoice)
    # Vorher-Stand fuer die Vorbelegung weiter unten: beim ERSTEN Speichern mit
    # Kunde greifen die Kundenvorgaben noch auf leere Felder, danach nie wieder
    # (sonst kaeme ein bewusst geleertes Feld beim naechsten Speichern zurueck).
    kunde_vorher = invoice.customer_id
    if aus_beleg:
        # Was aus dem signierten Beleg stammt, kommt aus dem Bestand und nicht
        # aus dem Formular (services/belegsperre.py).
        try:
            rohe_positionen = belegsperre.positionen_binden(invoice, rohe_positionen)
        except belegsperre.BelegsperreVerletzt as fehler:
            raise FormularFehler(str(fehler)) from fehler
    else:
        neue_kunde_id = kunde_id(form)
        try:
            kunde_zuordnung_pruefen(db, neue_kunde_id)
        except HTTPException as fehler:
            raise FormularFehler(fehler.detail) from fehler
        invoice.customer_id = neue_kunde_id
        invoice.service_period_start = service_period_start
        invoice.service_period_end = service_period_end
    return rohe_positionen, aus_beleg, kunde_vorher


def positionsangaben_pruefen(rohe_positionen) -> None:
    try:
        pruefe_einheiten(rohe_positionen)
        pruefe_positionsangaben(rohe_positionen)
    except HTTPException as fehler:
        raise FormularFehler(fehler.detail) from fehler


def steuerkategorie_uebernehmen(invoice: Invoice, form, aus_beleg: bool) -> None:
    # Festlegung 13: Die Steuerkategorie eines Auftragsentwurfs (Beleg mit
    # Auftragsschluessel) stammt aus der Vorgabe am Kunden (AE) und ist wie
    # die Beträge gebunden — ein anderer Wert aus dem Formular wäre dieselbe
    # Fälschung wie ein anderer Betrag. Beim 389-Entwurf bleibt sie dagegen
    # korrigierbar (belegsperre.py): Dort wird sie erst hier aus dem Status
    # des Kunden abgeleitet, und eine falsche Ableitung muss man richten
    # können.
    if not (aus_beleg and invoice.auftragsschluessel is not None):
        invoice.tax_category = form.get("tax_category", "S").strip() or "S"


def _hinweis_beim_tausch(invoice: Invoice, form, company: Company) -> str | None:
    """Kundenhinweis nur, wenn die Vorgabe der anderen Sprache ersetzt wird (#260).

    Ein leeres Feld bekommt im Bearbeiten weiter die Firmenvorgabe; das ist
    nicht Gegenstand von #260.
    """
    if invoice.customer is None:
        return None
    if not ist_vorgabe_der_anderen_sprache(
        form.get("payment_terms"), company, invoice.document_language or "de",
    ):
        return None
    return (invoice.customer.zahlungshinweis or "").strip() or None


def sprache_und_zahlung_uebernehmen(invoice: Invoice, form, company: Company) -> None:
    try:
        invoice.document_language = belegsprache_aus_form(
            form, fehlt=invoice.document_language or "de",
        )
        if ist_rechnungsauftrag(invoice):
            invoice.payment_terms = (form.get("payment_terms") or "").strip() or None
            return
        invoice.payment_terms = zahlungsbedingungen(
            form, company, invoice.document_language,
            kunden_hinweis=_hinweis_beim_tausch(invoice, form, company),
        )
        invoice.payment_terms = zahlungstext_beim_speichern(
            invoice.invoice_type, invoice.payment_terms, company,
            due_date=invoice.due_date, issue_date=invoice.issue_date,
            customer=invoice.customer,
            darstellung=darstellung(invoice.document_language or "de"),
        )
    except HTTPException as fehler:
        raise FormularFehler(fehler.detail) from fehler

    # Wie beim Anlegen: BR-CO-25, als Formularfehler statt eines 500ers durch
    # die DB-CHECK beim Commit. Der Entwurf bleibt unveraendert.
    try:
        zahlungsfrist_pruefen(invoice.due_date, invoice.payment_terms)
    except HTTPException:
        raise FormularFehler(FRIST_ODER_BEDINGUNGEN_FEHLT) from None


def kopf_uebernehmen(invoice: Invoice, form, company: Company, delivery_date, aus_beleg: bool) -> None:
    """Kopffelder des Entwurfs aus dem Formular übernehmen."""
    invoice.issue_date = date.fromisoformat(form.get("issue_date"))
    invoice.due_date = faelligkeit_aus_form(form)
    invoice.delivery_date = delivery_date
    steuerkategorie_uebernehmen(invoice, form, aus_beleg)
    sprache_und_zahlung_uebernehmen(invoice, form, company)
    invoice.buyer_reference = form.get("buyer_reference", "").strip() or None
    invoice.buyer_order_reference = form.get("buyer_order_reference", "").strip() or None
    invoice.notes = form.get("notes", "").strip() or None
    invoice.kopftext = (form.get("kopftext") or "").strip() or None
    invoice.fusstext = (form.get("fusstext") or "").strip() or None


def kundenvorgabe_nachtragen(db: Session, invoice: Invoice, kunde_vorher) -> None:
    # Erstmals mit Kunde gespeichert (Auftrag 2a): die Vorbelegung konnte beim
    # Anlegen nicht greifen, weil kein Kunde gewaehlt war. Sie fuellt jetzt nur
    # Felder, die noch leer sind; was der Nutzer hier eingetippt hat, gewinnt.
    if invoice.customer_id is not None and kunde_vorher is None:
        kunde = db.query(Customer).filter(Customer.id == invoice.customer_id).first()
        vorgabe = kundenvorgaben.entwurfs_vorbelegung(
            kunde, invoice.service_period_start, invoice.service_period_end,
        )
        if invoice.kopftext is None:
            invoice.kopftext = vorgabe.kopftext
        if invoice.fusstext is None:
            invoice.fusstext = vorgabe.fusstext


def summen_aus_formular(form, rohe_positionen) -> tuple[list[InvoiceItem], Belegsummen, Decimal | None, str | None]:
    # Abzug: unvollstaendiges Paar und unparsebarer Betrag wie oben, Wertefehler
    # aus belegsummen. Hier gibt es keinen Zaehler zu schuetzen, aber dieselbe
    # Meldung ueber das Formular statt eines 500ers.
    try:
        abzug_betrag, abzug_grund = abzug_aus_form(form)
        positionen = positionen_aus_formular(rohe_positionen)
        summen = belegsummen(positionen, abzug_betrag)
    except HTTPException as fehler:
        raise FormularFehler(fehler.detail) from fehler
    except ValueError as fehler:
        raise FormularFehler(str(fehler)) from fehler
    return positionen, summen, abzug_betrag, abzug_grund
