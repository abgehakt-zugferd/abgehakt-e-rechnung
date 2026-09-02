"""Baut eine Storno-/Gutschriftrechnung (EN16931 TypeCode 381) zu einer Originalrechnung.

Reine Logik ohne DB-Zugriff: erzeugt ein transientes Invoice mit gesetzter items-Collection.
Beträge bleiben POSITIV; die Stornowirkung trägt invoice_type="credit_note" (→ TypeCode 381
in zugferd_xml._get_type_code) plus die Referenz original_invoice_id (→ InvoiceReferencedDocument).
Das Original wird NICHT verändert.
"""
from datetime import date

from app.models.invoice import Invoice, InvoiceItem
from app.services.archive_frist import berechne_archive_until


def build_storno(original: Invoice, invoice_number: str, today: date) -> Invoice:
    storno = Invoice(
        invoice_number=invoice_number,
        customer_id=original.customer_id,
        issue_date=today,
        due_date=today,
        delivery_date=original.delivery_date,
        service_period_start=original.service_period_start,
        service_period_end=original.service_period_end,
        payment_terms=f"Gutschrift/Storno zur Rechnung {original.invoice_number}.",
        notes=f"Storno zur Rechnung {original.invoice_number} "
              f"vom {original.issue_date.strftime('%d.%m.%Y')}.",
        currency=original.currency,
        zugferd_profile="EN16931",
        tax_category=original.tax_category,
        invoice_type="credit_note",
        original_invoice_id=original.id,
        net_total=original.net_total,
        tax_total=original.tax_total,
        gross_total=original.gross_total,
        archive_until=berechne_archive_until(today),
        buyer_reference=original.buyer_reference,
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
