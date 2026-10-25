"""Zahlungsmittel, Steuerzusammenfassung, Zu-/Abschlaege, Zahlungsbedingungen, Summen."""
from collections import defaultdict
from decimal import Decimal

from app.models.company import Company
from app.models.invoice import Invoice
from app.services.auftragszahlung import ist_rechnungsauftrag
from app.services.bankverbindung import iban_fuer_ausgabe
from app.services.belegart import belegart, zahlung_an_kunde
from app.services.belegsummen import Belegsummen
from app.services.iban import IbanProfil

from app.services.zugferd_xml.format import esc, fmt_amount, fmt_date, item_tax_category, rate_percent_xml
from app.services.zugferd_xml.lieferung import billing_period_xml, reference_xml
from app.services.zugferd_xml.steuerbefreiung import EXEMPTION_REASONS, exemption_reason


def tax_summaries_xml(invoice: Invoice, summen: Belegsummen) -> str:
    inv_cat = getattr(invoice, "tax_category", "S")
    grouped: dict[Decimal, dict] = defaultdict(lambda: {"basis": Decimal("0"), "tax": Decimal("0")})
    for item in invoice.items:
        rate = item.tax_rate
        grouped[rate]["basis"] += item.net_amount
        grouped[rate]["tax"] += item.tax_amount

    parts = []
    for rate, totals in sorted(grouped.items()):
        tax_cat = item_tax_category(rate, inv_cat)
        exemption_block = ""
        code_block = ""
        if inv_cat in EXEMPTION_REASONS:
            grund = exemption_reason(invoice)
            if grund:
                exemption_block = f"\n                <ram:ExemptionReason>{esc(grund)}</ram:ExemptionReason>"
            # BT-121: nur Belegebene (BG-23). Positionsblock hat BT-151/BT-152;
            # VATEX-Codes fuer K/E/O sind nicht Teil dieses Auftrags.
            if inv_cat == "AE":
                code_block = (
                    "\n                <ram:ExemptionReasonCode>VATEX-EU-AE"
                    "</ram:ExemptionReasonCode>"
                )
        rate_line = rate_percent_xml(rate, inv_cat, "\n                ")
        # Bei Abzug rechnet belegsummen die Steuer neu auf der verminderten Basis;
        # dann gibt es per Definition nur einen Satz, also genau diese Gruppe.
        basis = summen.steuerbasis if summen.abzug > 0 else totals["basis"]
        tax = summen.steuer if summen.abzug > 0 else totals["tax"]
        # CII-Sequenz: ExemptionReasonCode nach CategoryCode, vor RateApplicablePercent
        parts.append(f"""
            <ram:ApplicableTradeTax>
                <ram:CalculatedAmount>{fmt_amount(tax)}</ram:CalculatedAmount>
                <ram:TypeCode>VAT</ram:TypeCode>{exemption_block}
                <ram:BasisAmount>{fmt_amount(basis)}</ram:BasisAmount>
                <ram:CategoryCode>{tax_cat}</ram:CategoryCode>{code_block}{rate_line}
            </ram:ApplicableTradeTax>""")
    return "\n".join(parts)


def allowance_charge_xml(invoice: Invoice, summen: Belegsummen) -> str:
    """BG-20 (EN 16931): Abzug auf Belegebene, genau ein Element (#147).

    CII-Sequenz in ApplicableHeaderTradeSettlement: nach BillingSpecifiedPeriod,
    vor SpecifiedTradePaymentTerms. ChargeIndicator false macht den Betrag zum
    Abzug; der Steuersatz kommt von den Positionen, belegsummen erzwingt bei
    Abzug einen einheitlichen Satz.
    """
    if summen.abzug <= 0:
        return ""
    inv_cat = getattr(invoice, "tax_category", "S")
    satz = invoice.items[0].tax_rate
    grund = getattr(invoice, "abzug_grund", None)
    rate_line = rate_percent_xml(satz, inv_cat, "\n                    ")
    return f"""
            <ram:SpecifiedTradeAllowanceCharge>
                <ram:ChargeIndicator>
                    <udt:Indicator>false</udt:Indicator>
                </ram:ChargeIndicator>
                <ram:ActualAmount>{fmt_amount(summen.abzug)}</ram:ActualAmount>
                <ram:Reason>{esc(grund)}</ram:Reason>
                <ram:CategoryTradeTax>
                    <ram:TypeCode>VAT</ram:TypeCode>
                    <ram:CategoryCode>{item_tax_category(satz, inv_cat)}</ram:CategoryCode>{rate_line}
                </ram:CategoryTradeTax>
            </ram:SpecifiedTradeAllowanceCharge>"""


def payment_means_xml(iban: str, bic: str | None = None, *, wer: str) -> str:
    if not iban:
        return ""
    iban_norm = iban_fuer_ausgabe(iban, wer=wer, profil=IbanProfil.REGISTRY)
    bic_block = ""
    if bic:
        bic_block = f"""
                <ram:PayeeSpecifiedCreditorFinancialInstitution>
                    <ram:BICID>{esc(bic)}</ram:BICID>
                </ram:PayeeSpecifiedCreditorFinancialInstitution>"""
    return f"""
            <ram:SpecifiedTradeSettlementPaymentMeans>
                <ram:TypeCode>58</ram:TypeCode>
                <ram:PayeePartyCreditorFinancialAccount>
                    <ram:IBANID>{esc(iban_norm)}</ram:IBANID>
                </ram:PayeePartyCreditorFinancialAccount>{bic_block}
            </ram:SpecifiedTradeSettlementPaymentMeans>"""


def company_payment_means_xml(company: Company) -> str:
    if not company.bank_iban:
        return ""
    return payment_means_xml(company.bank_iban, company.bank_bic, wer="Firma")


def gutschrift_zahlung_an_kunde(invoice: Invoice) -> bool:
    # Zahlungsfluss entscheidet belegart.zahlung_an_kunde ueber die
    # aufgeloeste Belegart — hier nur der Leser.
    return zahlung_an_kunde(getattr(invoice, "invoice_type", None))


def payment_terms_xml(invoice: Invoice) -> str:
    """Gutschrift ohne Fälligkeit: keine Zahlungsaufforderung in der XML (#48).

    Ohne due_date (Bauschritt 2b) entfällt BT-9 ganz: ein leeres
    DueDateDateTime wäre kein gültiges Datum, und der Zahlungshinweis in
    BT-20 (Description) trägt die Zahlungsregel allein (BR-CO-25).
    """
    text = invoice.payment_terms or "Zahlbar ohne Abzug."
    if belegart(invoice.invoice_type).intern == "credit_note" or invoice.due_date is None:
        return f"""
            <ram:SpecifiedTradePaymentTerms>
                <ram:Description>{esc(text)}</ram:Description>
            </ram:SpecifiedTradePaymentTerms>"""
    return f"""
            <ram:SpecifiedTradePaymentTerms>
                <ram:Description>{esc(text)}</ram:Description>
                <ram:DueDateDateTime>
                    <udt:DateTimeString format="102">{fmt_date(invoice.due_date)}</udt:DateTimeString>
                </ram:DueDateDateTime>
            </ram:SpecifiedTradePaymentTerms>"""


def settlement_payment_xml(invoice: Invoice, company: Company) -> str:
    customer = invoice.customer
    if gutschrift_zahlung_an_kunde(invoice):
        if customer and customer.bank_iban:
            return payment_means_xml(
                customer.bank_iban, customer.bank_bic, wer="Kunde"
            )
        return ""
    return company_payment_means_xml(company)


def monetary_summation_xml(invoice: Invoice, summen: Belegsummen) -> str:
    allowance_total = ""
    if summen.abzug > 0:
        allowance_total = (
            f"\n                <ram:AllowanceTotalAmount>{fmt_amount(summen.abzug)}</ram:AllowanceTotalAmount>"
        )
    # CII-Sequenz: GrandTotalAmount, dann TotalPrepaidAmount (BT-113), dann
    # DuePayableAmount (BT-115). Rechnungsauftrag: voll vorausgezahlt, BR-CO-16.
    if ist_rechnungsauftrag(invoice):
        prepaid = (
            f"\n                <ram:TotalPrepaidAmount>{fmt_amount(summen.brutto)}</ram:TotalPrepaidAmount>"
        )
        due = fmt_amount(Decimal("0"))
    else:
        prepaid = ""
        due = fmt_amount(summen.brutto)
    return f"""            <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
                <ram:LineTotalAmount>{fmt_amount(summen.positionen_netto)}</ram:LineTotalAmount>{allowance_total}
                <ram:TaxBasisTotalAmount>{fmt_amount(summen.steuerbasis)}</ram:TaxBasisTotalAmount>
                <ram:TaxTotalAmount currencyID="{esc(invoice.currency)}">{fmt_amount(summen.steuer)}</ram:TaxTotalAmount>
                <ram:GrandTotalAmount>{fmt_amount(summen.brutto)}</ram:GrandTotalAmount>{prepaid}
                <ram:DuePayableAmount>{due}</ram:DuePayableAmount>
            </ram:SpecifiedTradeSettlementHeaderMonetarySummation>"""


def header_trade_settlement_xml(
    invoice: Invoice, company: Company, summen: Belegsummen
) -> str:
    return f"""        <ram:ApplicableHeaderTradeSettlement>
            <ram:PaymentReference>{esc(invoice.invoice_number)}</ram:PaymentReference>
            <ram:InvoiceCurrencyCode>{esc(invoice.currency)}</ram:InvoiceCurrencyCode>
{settlement_payment_xml(invoice, company)}
{tax_summaries_xml(invoice, summen)}
{billing_period_xml(invoice)}
{allowance_charge_xml(invoice, summen)}
{payment_terms_xml(invoice)}
{monetary_summation_xml(invoice, summen)}{reference_xml(invoice)}
        </ram:ApplicableHeaderTradeSettlement>"""
