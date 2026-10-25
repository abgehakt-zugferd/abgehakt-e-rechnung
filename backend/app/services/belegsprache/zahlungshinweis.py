"""Zahlungstext im Gutschriftverfahren (389) vs. Firmenvorgabe (#231).

PDF und BT-20 lesen denselben Text. Traegt der Beleg noch die Firmenvorgabe
(oder keinen Text), entsteht der Gutschrift-Wortlaut; freier Nutzereingriff
bleibt unangetastet.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services.belegart import UnknownInvoiceTypeError, belegart
from app.services.belegsprache.modell import Belegdarstellung
from app.zeit import heute


def ist_firmen_zahlung_vorgabe(text: str | None, company) -> bool:
    """True, wenn der gespeicherte Text die Firmenvorgabe (de/en) ist oder fehlt."""
    gespeichert = (text or "").strip()
    if not gespeichert:
        return True
    vorgaben = set()
    for attr in ("payment_terms_default", "payment_terms_default_en"):
        wert = getattr(company, attr, None)
        if wert and str(wert).strip():
            vorgaben.add(str(wert).strip())
    return gespeichert in vorgaben


def _faelligkeit(invoice) -> date:
    due = getattr(invoice, "due_date", None)
    if due is not None:
        return due
    ausstellung = getattr(invoice, "issue_date", None)
    if ausstellung is not None:
        return ausstellung + timedelta(days=14)
    return heute()


def _iban_leistender(invoice) -> str | None:
    kunde = getattr(invoice, "customer", None)
    if kunde is None:
        return None
    iban = (getattr(kunde, "bank_iban", None) or "").strip()
    return iban or None


def zahlungstext_self_billing(invoice, company, d: Belegdarstellung) -> str | None:
    """Verbindlicher Zahlungstext fuer 389, sonst None (Caller-Fallback)."""
    try:
        if belegart(getattr(invoice, "invoice_type", None)).intern != "self_billing":
            return None
    except UnknownInvoiceTypeError:
        return None
    gespeichert = (getattr(invoice, "payment_terms", None) or "").strip()
    if gespeichert and not ist_firmen_zahlung_vorgabe(gespeichert, company):
        return gespeichert
    return d.zahlung_gutschriftverfahren(
        datum=_faelligkeit(invoice),
        iban=_iban_leistender(invoice),
    )


def zahlungstext_beim_speichern(
    invoice_type: str | None,
    payment_terms: str | None,
    company,
    *,
    due_date: date | None,
    issue_date: date | None,
    customer,
    darstellung: Belegdarstellung,
) -> str | None:
    """Beim Anlegen/Speichern: Vorgabe am 389-Beleg durch Gutschrift-Text ersetzen."""
    try:
        if belegart(invoice_type).intern != "self_billing":
            return payment_terms
    except UnknownInvoiceTypeError:
        return payment_terms
    if not ist_firmen_zahlung_vorgabe(payment_terms, company):
        return payment_terms
    faellig = due_date
    if faellig is None and issue_date is not None:
        faellig = issue_date + timedelta(days=14)
    if faellig is None:
        faellig = heute()
    iban = None
    if customer is not None:
        iban = (getattr(customer, "bank_iban", None) or "").strip() or None
    return darstellung.zahlung_gutschriftverfahren(datum=faellig, iban=iban)
