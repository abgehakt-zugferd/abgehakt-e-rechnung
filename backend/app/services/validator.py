"""
Regelbasierte Rechnungsprüfung nach § 14 UStG und ZUGFeRD EN16931-Anforderungen.

Bewusst regelbasiert und nachlesbar: jede Meldung lässt sich auf eine Regel im
Paket pruefregeln und von dort auf eine Vorschrift zurückführen. Eine Prüfung,
deren Begründung niemand nachvollziehen kann, ist in einem Steuerkontext wertlos.

validate_invoice löst Belegart und Kleinbetrag einmal auf, ruft die Regelgruppen
in fester Reihenfolge und trennt die gesammelten Befunde erst am Ende nach
Severity in Fehler und Warnungen. Die Aufrufruordnung ist Vertragsbestandteil:
Tests prüfen Befund-Listen.
"""
from decimal import Decimal

from app.models.company import Company
from app.models.invoice import Invoice
from app.services.belegart import UnknownInvoiceTypeError, belegart
from app.services.ersatzrechnung import pruefe_finalisierbar
from app.services.pruefregeln import (
    aussteller,
    belegbezug,
    empfaenger,
    empfehlungen,
    kopf,
    positionen,
    profil,
    steuerkategorie,
)
from app.services.pruefregeln.abzug_summen import pruefe_abzug_summen
from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext
from app.services.steuerstatus import pruefe_honorargutschrift

SIMPLIFIED_INVOICE_THRESHOLD = Decimal("250")  # § 33 UStDV


def validate_invoice(invoice: Invoice, company: Company) -> tuple[list[Issue], list[Issue]]:
    kontext = _pruefkontext(invoice, company)
    befunde: list[Issue] = []
    befunde.extend(profil.pruefe_profil(kontext))
    befunde.extend(aussteller.pruefe_aussteller(kontext))
    befunde.extend(empfaenger.pruefe_leistungsempfaenger(kontext))
    befunde.extend(kopf.pruefe_kopf(kontext))
    befunde.extend(positionen.pruefe_positionen(kontext))
    befunde.extend(pruefe_abzug_summen(kontext))
    befunde.extend(steuerkategorie.pruefe_steuerkategorie(kontext))
    befunde.extend(belegbezug.pruefe_belegbezug(kontext))

    # Honorargutschrift (389): Steuerstatus und Kennung des Autors. Eigene
    # Regeln im Modul steuerstatus; hier nur der Aufruf, damit validator.py
    # nicht weiter waechst und keine zirkulaeren Imports entstehen.
    if kontext.belegart is not None and kontext.belegart.intern == "self_billing":
        befunde.extend(pruefe_honorargutschrift(invoice))

    # Ersatzrechnung (docs/specs/ersatzrechnung.md): Regeln im eigenen Modul.
    befunde.extend(pruefe_finalisierbar(invoice))

    befunde.extend(empfehlungen.pruefe_empfehlungen(kontext))

    errors = [b for b in befunde if b.severity == "error"]
    warnings = [b for b in befunde if b.severity == "warning"]
    return errors, warnings


def _pruefkontext(invoice: Invoice, company: Company) -> Pruefkontext:
    """Loest einmal auf, was mehrere Regeln brauchen."""
    # Belegart einmal aufloesen: sie steuert die Datumspruefungen (386 unten)
    # und die Originalbezug-Konsistenz (weiter unten). Unbekannte Typen werden
    # nicht hier, sondern als INVOICE_TYPE_INVALID gemeldet.
    invoice_type = getattr(invoice, "invoice_type", None)
    try:
        art = belegart(invoice_type)
    except UnknownInvoiceTypeError:
        art = None
    # „nicht uebersteigt" (§ 33 UStDV) heisst bis EINSCHLIESSLICH 250 €. Mit `<`
    # verlangte die Pruefung bei genau 250,00 € brutto ein Leistungsdatum und wies
    # die Finalisierung ab, fuer eine Rechnung, die das Gesetz davon befreit (#23).
    return Pruefkontext(
        invoice=invoice,
        company=company,
        rechnungstyp=invoice_type,
        belegart=art,
        kleinbetrag=invoice.gross_total <= SIMPLIFIED_INVOICE_THRESHOLD,
        steuerkategorie=getattr(invoice, "tax_category", "S"),
        # Wie steuerkategorie mit getattr gelesen, damit Testattrappen ohne
        # die Felder weiter laufen. Betrag und Grund sind ein Paar:
        # EN 16931 BR-33 verlangt den Grund zum Abzug.
        abzug_betrag=getattr(invoice, "abzug_betrag", None),
        abzug_grund=getattr(invoice, "abzug_grund", None),
    )
