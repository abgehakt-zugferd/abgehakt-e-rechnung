"""Lieferung (HeaderTradeDelivery) und Belegreferenzen (BG-3)."""
from app.laender import normalisiere_land
from app.models.invoice import Invoice
from app.services import anzahlungen

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
    """ApplicableHeaderTradeDelivery: Lieferdatum (BT-72) oder Lieferland (BG-13).

    Eine Regel für alle Fälle (#299):
    - BT-72 (ActualDeliverySupplyChainEvent) nur, wenn `invoice.delivery_date` gesetzt
      ist. Aus dem Leistungszeitraum wird nichts abgeleitet: ein Lieferdatum, das nicht
      im Datensatz steht, wäre eine erfundene Angabe (bei der Anzahlungsrechnung
      zudem die Behauptung einer schon erfolgten Lieferung).
    - Ohne delivery_date steht, wenn es einen Kunden gibt, nur sein Land im Block
      (ShipToTradeParty/PostalTradeAddress/CountryID, kein Name, keine Straße).
      Grund: Der Block darf nicht leer sein. Das FeRD-Schematron (Factur-X 1.08,
      FACTUR-X_EN16931.sch, BR-FX-EN-04) verlangt „if BT-72 is not used, at least the
      country of delivery (BT-80) must be specified for technical reasons“; ein leerer
      Block löst in Mustang PEPPOL-EN16931-R008 aus (KoSIT nimmt die Regel für diesen
      Block aus). BR-57 verlangt dabei eine nicht leere CountryID.
    - Kategorie K schreibt ShipTo immer (BR-IC-12, Lieferland BT-80); es gibt EINEN
      ShipTo-Zweig, nichts steht doppelt.
    - Mit delivery_date bei S/AE bleibt der Block wie bisher ohne ShipTo.

    Ohne Datum und ohne Kundenland bleibt der Block leer. Er muss als Element stehen
    (das CII-Schema verlangt ihn zwischen Agreement und Settlement), und das ist der
    einzige leere Fall; ihn fängt die Warnungs-Rückfrage beim Finalisieren ab. Die
    Kleinbetragsrechnung ohne Leistungsdatum (§ 33 UStDV, #47) hat in der Regel ein
    Kundenland und fällt deshalb nicht darunter.
    """
    inv_cat = getattr(invoice, "tax_category", "S")
    customer = invoice.customer
    ship_to = ""
    if customer and (inv_cat == "K" or not invoice.delivery_date):
        ship_to = f"""
            <ram:ShipToTradeParty>
                <ram:PostalTradeAddress>
                    <ram:CountryID>{esc(normalisiere_land(customer.country))}</ram:CountryID>
                </ram:PostalTradeAddress>
            </ram:ShipToTradeParty>"""
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
