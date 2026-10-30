"""Zahlungstext im Gutschriftverfahren (389) vs. Firmenvorgabe (#231).

Ersetzung nur beim Speichern und vor dem Finalisieren eines Entwurfs
(persistiert in payment_terms). PDF und BT-20 lesen den gespeicherten Text.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.services.auftragszahlung import ist_rechnungsauftrag
from app.services.belegart import UnknownInvoiceTypeError, belegart
from app.services.belegsprache import darstellung as darstellung_fuer
from app.services.belegsprache import resolve_belegsprache
from app.services.belegsprache.modell import Belegdarstellung
from app.services.belegsprache.zahlungsvorgabe import (
    ZahlungsvorgabeFehlt,
    ist_vorgabe_der_anderen_sprache,
    zahlungstext_in_belegsprache,
)
from app.services.rechnung.fehler import RechnungFehler
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


def zahlungstext_vor_finalisieren(invoice, company) -> None:
    """Entwurf vor PDF/XML: Sprach-Tausch (#260), dann Gutschrift-Text (#231).

    Rechnungsauftraege behalten ihren Weg (Hinweis aus dem Auftrag). Fehlt die
    englische Vorgabe und der Kundenhinweis, bleibt der Entwurf unveraendert.
    """
    if ist_rechnungsauftrag(invoice):
        return
    sprache = resolve_belegsprache(getattr(invoice, "document_language", None) or "de")
    text = getattr(invoice, "payment_terms", None)
    customer = getattr(invoice, "customer", None)
    if ist_vorgabe_der_anderen_sprache(text, company, sprache):
        try:
            text = zahlungstext_in_belegsprache(
                text, company, sprache,
                getattr(customer, "zahlungshinweis", None),
            )
        except ZahlungsvorgabeFehlt as fehler:
            raise RechnungFehler(400, str(fehler)) from fehler
    invoice.payment_terms = zahlungstext_beim_speichern(
        getattr(invoice, "invoice_type", None),
        text,
        company,
        due_date=getattr(invoice, "due_date", None),
        issue_date=getattr(invoice, "issue_date", None),
        customer=customer,
        darstellung=darstellung_fuer(sprache),
    )
