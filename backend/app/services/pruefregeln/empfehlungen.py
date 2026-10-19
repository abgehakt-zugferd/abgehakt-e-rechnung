"""Empfehlungen: Warnungen ohne Normpflicht (Zahlungsbedingungen, Bankverbindungen)."""
from app.models.invoice import Invoice
from app.services.belegart import GUTSCHRIFT_TYPEN
from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext


def pruefe_empfehlungen(kontext: Pruefkontext) -> list[Issue]:
    invoice = kontext.invoice
    company = kontext.company
    # Empfehlungen
    befunde: list[Issue] = []
    if not invoice.payment_terms:
        befunde.append(Issue("NO_PAYMENT_TERMS", "warning", "Zahlungsbedingungen fehlen (empfohlen).", "payment_terms"))
    if company and not company.bank_iban and not _gutschrift_auszahlung(invoice):
        befunde.append(Issue("NO_BANK_DETAILS", "warning", "Bankverbindung in den Einstellungen nicht hinterlegt (empfohlen für SEPA-Zahlungen).", "company.bank_iban"))
    if _gutschrift_auszahlung(invoice) and invoice.customer and not invoice.customer.bank_iban:
        befunde.append(Issue(
            "CUSTOMER_BANK_MISSING", "warning",
            "Bankverbindung des Kunden fehlt (IBAN für Gutschrift-Auszahlung und EPC-QR empfohlen).",
            "customer.bank_iban",
        ))
    return befunde


def _gutschrift_auszahlung(invoice: Invoice) -> bool:
    # Die Menge steht einmal in belegart.GUTSCHRIFT_TYPEN, hier nur der Leser.
    return getattr(invoice, "invoice_type", None) in GUTSCHRIFT_TYPEN
