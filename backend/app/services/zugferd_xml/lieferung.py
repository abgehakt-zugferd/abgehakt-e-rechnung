"""Lieferung (HeaderTradeDelivery) und Belegreferenzen (BG-3)."""
from app.models.invoice import Invoice

from app.services.zugferd_xml.format import esc, fmt_date


def billing_period_xml(invoice: Invoice) -> str:
    start = invoice.service_period_start
    end = invoice.service_period_end
    if not start or not end:
        return ""
    return f"""
            <ram:BillingSpecifiedPeriod>
                <ram:StartDateTime>
                    <udt:DateTimeString format="102">{fmt_date(start)}</udt:DateTimeString>
                </ram:StartDateTime>
                <ram:EndDateTime>
                    <udt:DateTimeString format="102">{fmt_date(end)}</udt:DateTimeString>
                </ram:EndDateTime>
            </ram:BillingSpecifiedPeriod>"""


def delivery_xml(invoice: Invoice) -> str:
    inv_cat = getattr(invoice, "tax_category", "S")
    customer = invoice.customer
    ship_to = ""
    if inv_cat == "K" and customer:
        # BR-IC-12: ig. Lieferung braucht Lieferland (BT-80).
        ship_to = f"""
            <ram:ShipToTradeParty>
                <ram:PostalTradeAddress>
                    <ram:CountryID>{esc(customer.country)}</ram:CountryID>
                </ram:PostalTradeAddress>
            </ram:ShipToTradeParty>"""
    # Der Block bleibt auch dann stehen, wenn nichts darin steht: das CII-Schema
    # verlangt <ram:ApplicableHeaderTradeDelivery> zwischen Agreement und
    # Settlement. Fehlte er, war die Datei schon am Schema unzulässig, nicht erst
    # an einer Geschäftsregel. Getroffen hat das die Kleinbetragsrechnung ohne
    # Leistungsdatum, die § 33 UStDV ausdrücklich erlaubt (#47).
    delivery_event = ""
    if invoice.delivery_date:
        delivery_event = f"""
            <ram:ActualDeliverySupplyChainEvent>
                <ram:OccurrenceDateTime>
                    <udt:DateTimeString format="102">{fmt_date(invoice.delivery_date)}</udt:DateTimeString>
                </ram:OccurrenceDateTime>
            </ram:ActualDeliverySupplyChainEvent>"""
    return f"""
        <ram:ApplicableHeaderTradeDelivery>{ship_to}{delivery_event}
        </ram:ApplicableHeaderTradeDelivery>"""


def reference_xml(invoice: Invoice) -> str:
    """
    P5: BG-3 – Referenz auf die vorausgegangene Rechnung (Stornorechnung/Gutschrift).

    Gem. EN16931 / UN-CEFACT CII trägt die Referenz auf eine vorausgegangene Rechnung
    das Element <ram:InvoiceReferencedDocument> (BT-25 Rechnungsnummer, BT-26 Datum) und
    steht in <ram:ApplicableHeaderTradeSettlement> NACH der Monetary Summation.

    Wichtig: NICHT BuyerOrderReferencedDocument verwenden – das ist BT-13 (Bestellnummer);
    ein konformer Empfänger (DATEV) würde die Originalrechnungsnummer sonst als Bestellnummer
    interpretieren und das Matching Storno↔Original bräche. BuyerOrderReferencedDocument
    wird hier für die echte Bestellnummer genutzt (`_buyer_order_reference_xml`, #101),
    nicht für die Referenz auf die vorausgegangene Rechnung.

    Der TypeCode (BT-3) der Storno-/Gutschriftrechnung wird separat über _get_type_code
    auf 381 gesetzt.
    """
    # Folgebeleg (381/384/389) oder Ersatzrechnung (380/386, docs/specs/ersatzrechnung.md):
    # beide verweisen per BT-25 auf genau eine vorausgegangene Rechnung.
    if invoice.original_invoice_id:
        original = invoice.original_invoice
    elif getattr(invoice, "ersetzt_invoice_id", None):
        original = invoice.ersetzte_rechnung
    else:
        return ""
    if not original:
        return ""

    return f"""
            <ram:InvoiceReferencedDocument>
                <ram:IssuerAssignedID>{esc(original.invoice_number)}</ram:IssuerAssignedID>
                <ram:FormattedIssueDateTime>
                    <qdt:DateTimeString format="102">{fmt_date(original.issue_date)}</qdt:DateTimeString>
                </ram:FormattedIssueDateTime>
            </ram:InvoiceReferencedDocument>"""
