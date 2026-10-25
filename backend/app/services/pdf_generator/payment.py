"""Zahlungsblock inklusive EPC-QR fuer das Rechnungs-PDF."""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Image, KeepTogether, Paragraph, Table, TableStyle

from app.services.bankverbindung import iban_fuer_ausgabe
from app.services.belegart import belegart
from app.services.belegsprache.zahlungshinweis import zahlungstext_self_billing
from app.services.epc_qr import build_epc_payload, qr_png_bytes
from app.services.iban import IbanProfil

from .layout import QR_KANTE, description_markup
from .logic import ist_gutschrift, zahlung_an_kunde_beleg, zahlungs_empfaenger


def payment_text(invoice, company, d):
    ersetzt = zahlungstext_self_billing(invoice, company, d)
    if ersetzt is not None:
        return ersetzt
    if zahlung_an_kunde_beleg(invoice) and zahlungs_empfaenger(invoice, company):
        text = invoice.payment_terms or d.fallback_gutschrift_ueberweisung
    elif ist_gutschrift(invoice):
        text = invoice.payment_terms or d.fallback_gutschrift_ohne
    else:
        text = invoice.payment_terms or d.fallback_zahlbar
    if belegart(invoice.invoice_type).intern == "credit_note" and not invoice.payment_terms:
        return "Stornorechnung zur ursprünglichen Rechnung." if d.code == "de" else "Cancellation of the original invoice."
    return text


def zahlungsblock(invoice, company, small, d, payment_text_value, schrift):
    """Zahlungstext, Bankdaten und Verwendungszweck rechts, der Girocode links.

    Eine Tabelle in KeepTogether: vorher standen Text, Bankdaten, QR-Code und
    Bildunterschrift einzeln im Fluss, und bei langen Rechnungen landete die
    Bildunterschrift allein auf der nächsten Seite. Ohne Empfänger bleibt nur der
    Zahlungstext; ohne gültigen Girocode (EPC strenger als REGISTRY) der Klartext.
    """
    text = [Paragraph(description_markup(payment_text_value), small)]
    ziel = zahlungs_empfaenger(invoice, company)
    if not ziel:
        return text
    name, iban, bic, bank_name = ziel
    iban_norm = _iban_registry(invoice, iban)
    text.extend(_banktext(d, invoice.invoice_number, iban_norm, bic, bank_name, small))
    payload = _payload(name, iban_norm, bic, invoice)
    if payload is None:
        return [KeepTogether(text)]
    return [_qr_tabelle(payload, d.label_scan_to_pay, small, schrift, text)]


def _iban_registry(invoice, iban):
    wer = "Kunde" if zahlung_an_kunde_beleg(invoice) else "Firma"
    # Option A: Registry-ungueltige Bestands-IBAN bricht die Erzeugung ab
    # (nicht still im Klartext weitergeben und nur den QR unterdruecken).
    return iban_fuer_ausgabe(iban, wer=wer, profil=IbanProfil.REGISTRY)


def _banktext(d, invoice_number, iban_norm, bic, bank_name, small):
    bank_parts = [f"IBAN: {iban_norm}"]
    if bic:
        bank_parts.append(f"BIC: {bic}")
    if bank_name:
        bank_parts.append(bank_name)
    return [
        Paragraph(escape(" · ".join(bank_parts)), small),
        Paragraph(escape(f"{d.label_verwendungszweck} {invoice_number}"), small),
    ]


def _payload(name, iban_norm, bic, invoice):
    try:
        return build_epc_payload(
            beneficiary_name=name,
            iban=iban_norm,
            bic=bic,
            amount=invoice.gross_total,
            currency=getattr(invoice, "currency", "EUR") or "EUR",
            remittance=invoice.invoice_number,
        )
    except ValueError:
        return None


def _qr_tabelle(payload, scan_label, small, schrift, text):
    qr = [
        Image(io.BytesIO(qr_png_bytes(payload)), width=QR_KANTE, height=QR_KANTE),
        Paragraph(escape(scan_label), small),
    ]
    breite = A4[0] - 4 * cm
    # So breit wie QR-Code oder Bildunterschrift, je nachdem was breiter ist:
    # umgebrochen stand „Zum Überweisen / scannen.“ auf zwei Zeilen.
    links = max(QR_KANTE, pdfmetrics.stringWidth(scan_label, schrift, small.fontSize)) + 0.6 * cm
    tabelle = Table([[qr, text]], colWidths=[links, breite - links])
    tabelle.hAlign = "LEFT"
    tabelle.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), schrift),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (0, 0), 0.6 * cm),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
    ]))
    return KeepTogether([tabelle])
