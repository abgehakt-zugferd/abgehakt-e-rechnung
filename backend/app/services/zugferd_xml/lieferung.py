"""Lieferung (HeaderTradeDelivery) und Belegreferenzen (BG-3)."""
from app.models.invoice import Invoice
from app.services import anzahlungen
from app.services.belegart import belegart

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
    # Leistungsdatum, die § 33 UStDV ausdrücklich erlaubt (#47). Genau dieser Fall
    # (weder Leistungsdatum noch Leistungszeitraum) bleibt ein leerer Block; Mustang
    # meldet dazu PEPPOL-EN16931-R008 als Warnung, und der Fall wird nicht aufgefüllt,
    # weil es kein Datum gibt, das stimmen könnte.
    #
    # Hat die Rechnung nur einen Leistungszeitraum, steht dessen Ende als
    # Lieferdatum im Block (#299), sonst bliebe er leer. Das betrifft nur das XML:
    # `invoice.delivery_date` bleibt unverändert.
    #
    # Ausnahme Anzahlungsrechnung (386): Ihr Zeitraum liegt in der Zukunft (BG-14
    # „voraussichtlich“); ein ActualDeliverySupplyChainEvent würde behaupten, es sei
    # bereits geliefert. Dort bleibt der Block ohne Ereignis, bis das fachlich
    # geklärt ist (offen, siehe #299).
    lieferdatum = invoice.delivery_date
    if not lieferdatum and belegart(invoice.invoice_type).intern != "prepayment":
        lieferdatum = invoice.service_period_end
    delivery_event = ""
    if lieferdatum:
        delivery_event = f"""
            <ram:ActualDeliverySupplyChainEvent>
                <ram:OccurrenceDateTime>
                    <udt:DateTimeString format="102">{fmt_date(lieferdatum)}</udt:DateTimeString>
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
        originale = [invoice.original_invoice]
    elif getattr(invoice, "ersetzt_invoice_id", None):
        originale = [invoice.ersetzte_rechnung]
    else:
        # Schlussrechnung (#259): je verrechnete Anzahlung eine vorausgegangene Rechnung.
        originale = anzahlungen.verrechnete(invoice)
    return "".join(_vorausgegangene_xml(o) for o in originale if o)


def _vorausgegangene_xml(original: Invoice) -> str:
    return f"""
            <ram:InvoiceReferencedDocument>
                <ram:IssuerAssignedID>{esc(original.invoice_number)}</ram:IssuerAssignedID>
                <ram:FormattedIssueDateTime>
                    <qdt:DateTimeString format="102">{fmt_date(original.issue_date)}</qdt:DateTimeString>
                </ram:FormattedIssueDateTime>
            </ram:InvoiceReferencedDocument>"""
