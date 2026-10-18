"""Positionszeilen (IncludedSupplyChainTradeLineItem)."""
from decimal import Decimal

from app.models.invoice import Invoice

from app.services.zugferd_xml.format import (
    esc,
    fmt_amount,
    fmt_date,
    item_tax_category,
    rate_percent_xml,
    unit_code,
)
from app.services.zugferd_xml.steuerbefreiung import EXEMPTION_REASONS, exemption_reason


def seller_item_id_xml(item) -> str:
    """BT-155 vor `ram:Name` (CII-Sequenz GlobalID, SellerAssignedID, …, Name).
    Ohne schemeID (CII-DT-005). Ohne Nummer kein Element."""
    nummer = (getattr(item, "artikelnummer", None) or "").strip()
    if not nummer:
        return ""
    return f"""
                <ram:SellerAssignedID>{esc(nummer)}</ram:SellerAssignedID>"""


def line_period_xml(item) -> str:
    """BT-134/135 zwischen ApplicableTradeTax und LineMonetarySummation (CII-Sequenz)."""
    von = getattr(item, "leistung_von", None)
    bis = getattr(item, "leistung_bis", None)
    if not von or not bis:
        return ""
    return f"""
                <ram:BillingSpecifiedPeriod>
                    <ram:StartDateTime>
                        <udt:DateTimeString format="102">{fmt_date(von)}</udt:DateTimeString>
                    </ram:StartDateTime>
                    <ram:EndDateTime>
                        <udt:DateTimeString format="102">{fmt_date(bis)}</udt:DateTimeString>
                    </ram:EndDateTime>
                </ram:BillingSpecifiedPeriod>"""


def line_note_xml(item) -> str:
    """BT-127: Die Gruppe der Position als Positionsnotiz, im
    AssociatedDocumentLineDocument NACH LineID (CII-Sequenz). EN 16931 kennt
    keine Zwischensummen, deshalb steht die Gruppe hier und nirgends als
    Rechenzeile. Ohne Gruppe kein Element (kein leeres IncludedNote)."""
    gruppe = (getattr(item, "gruppe", None) or "").strip()
    if not gruppe:
        return ""
    return f"""
                <ram:IncludedNote>
                    <ram:Content>Gruppe: {esc(gruppe)}</ram:Content>
                </ram:IncludedNote>"""


def line_items_xml(invoice: Invoice) -> str:
    inv_cat = getattr(invoice, "tax_category", "S")
    parts = []
    for item in invoice.items:
        code = unit_code(item.unit)
        tax_cat = item_tax_category(item.tax_rate, inv_cat)
        exemption_block = ""
        if inv_cat in EXEMPTION_REASONS:
            grund = exemption_reason(invoice)
            if grund:
                exemption_block = f"\n                    <ram:ExemptionReason>{esc(grund)}</ram:ExemptionReason>"
        rate_line = rate_percent_xml(item.tax_rate, inv_cat, "\n                    ")
        # BR-27 (EN 16931): Der Einzelpreis (BT-146) darf nicht negativ sein.
        # Eine Erstattungsposition traegt ihr Vorzeichen in der Anwendung auf
        # dem Einzelpreis (Festlegung 11, pruefregeln/positionen.py erlaubt
        # das nur bei einer 380 aus einem Beleg); auf dem Draht gehoert es
        # auf die Menge (BT-129), denn BR-26 verlangt Positionsbetrag =
        # Menge x Preis: (-Menge) x |Preis| = derselbe Negative Betrag.
        preis = item.unit_price
        menge = item.quantity
        if preis < 0:
            preis = -preis
            menge = -menge
        parts.append(f"""
        <ram:IncludedSupplyChainTradeLineItem>
            <ram:AssociatedDocumentLineDocument>
                <ram:LineID>{item.position}</ram:LineID>{line_note_xml(item)}
            </ram:AssociatedDocumentLineDocument>
            <ram:SpecifiedTradeProduct>{seller_item_id_xml(item)}
                <ram:Name>{esc(item.description)}</ram:Name>
            </ram:SpecifiedTradeProduct>
            <ram:SpecifiedLineTradeAgreement>
                <ram:NetPriceProductTradePrice>
                    <ram:ChargeAmount>{fmt_amount(preis)}</ram:ChargeAmount>
                </ram:NetPriceProductTradePrice>
            </ram:SpecifiedLineTradeAgreement>
            <ram:SpecifiedLineTradeDelivery>
                <ram:BilledQuantity unitCode="{code}">{str(menge.quantize(Decimal("0.0001")))}</ram:BilledQuantity>
            </ram:SpecifiedLineTradeDelivery>
            <ram:SpecifiedLineTradeSettlement>
                <ram:ApplicableTradeTax>
                    <ram:TypeCode>VAT</ram:TypeCode>{exemption_block}
                    <ram:CategoryCode>{tax_cat}</ram:CategoryCode>{rate_line}
                </ram:ApplicableTradeTax>{line_period_xml(item)}
                <ram:SpecifiedTradeSettlementLineMonetarySummation>
                    <ram:LineTotalAmount>{fmt_amount(item.net_amount)}</ram:LineTotalAmount>
                </ram:SpecifiedTradeSettlementLineMonetarySummation>
            </ram:SpecifiedLineTradeSettlement>
        </ram:IncludedSupplyChainTradeLineItem>""")
    return "\n".join(parts)
