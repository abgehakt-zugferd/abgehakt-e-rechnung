"""Baut eine Storno-/Gutschriftrechnung (EN16931 TypeCode 381) zu einer Originalrechnung.

Reine Logik ohne DB-Zugriff: erzeugt ein transientes Invoice mit gesetzter items-Collection.
Beträge bleiben POSITIV; die Stornowirkung trägt invoice_type="credit_note" (→ TypeCode 381
in zugferd_xml._get_type_code) plus die Referenz original_invoice_id (→ InvoiceReferencedDocument).
Das Original wird NICHT verändert.

Automatisierte Zahlungsbedingungen und Bemerkung kommen aus Belegdarstellung
zur Sprache des Originals (docs/specs/belegsprache.md). Positionen und sonstige
Nutzerdaten bleiben unverändert.
"""
from datetime import date

from app.models.invoice import Invoice, InvoiceItem
from app.services.archive_frist import berechne_archive_until
from app.services.belegsprache import darstellung, resolve_belegsprache


def build_storno(original: Invoice, invoice_number: str, today: date) -> Invoice:
    sprache = resolve_belegsprache(getattr(original, "document_language", None) or "de")
    d = darstellung(sprache)
    datum_text = d.format_datum(original.issue_date)
    storno = Invoice(
        invoice_number=invoice_number,
        customer_id=original.customer_id,
        issue_date=today,
        due_date=today,
        delivery_date=original.delivery_date,
        service_period_start=original.service_period_start,
        service_period_end=original.service_period_end,
        payment_terms=d.storno_zahlungsbedingungen.format(nummer=original.invoice_number),
        notes=d.storno_bemerkung.format(
            nummer=original.invoice_number, datum=datum_text,
        ),
        currency=original.currency,
        zugferd_profile="EN16931",
        tax_category=original.tax_category,
        invoice_type="credit_note",
        document_language=sprache,
        original_invoice_id=original.id,
        net_total=original.net_total,
        tax_total=original.tax_total,
        gross_total=original.gross_total,
        archive_until=berechne_archive_until(today),
        buyer_reference=original.buyer_reference,
        buyer_order_reference=original.buyer_order_reference,
        status="draft",
    )
    storno.items = [
        InvoiceItem(
            position=item.position,
            description=item.description,
            unit=item.unit,
            quantity=item.quantity,
            unit_price=item.unit_price,
            tax_rate=item.tax_rate,
            net_amount=item.net_amount,
            tax_amount=item.tax_amount,
            gross_amount=item.gross_amount,
        )
        for item in original.items
    ]
    return storno
