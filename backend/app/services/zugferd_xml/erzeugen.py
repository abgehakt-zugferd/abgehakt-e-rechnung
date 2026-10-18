"""Orchestrierung: CII-XML aus Rechnung und Firma zusammenbauen."""
from app.models.company import Company
from app.models.invoice import Invoice
from app.services.belegrollen import besetzung
from app.services.belegsummen import belegsummen

from app.services.zugferd_xml.kopf import exchanged_document_xml
from app.services.zugferd_xml.lieferung import delivery_xml
from app.services.zugferd_xml.parteien import header_trade_agreement_xml
from app.services.zugferd_xml.positionen import line_items_xml
from app.services.zugferd_xml.steuerbefreiung import (
    NonCompliantProfileError,
    PROFILE_IDS,
)
from app.services.zugferd_xml.zahlung_summen import header_trade_settlement_xml


def generate_xml(invoice: Invoice, company: Company) -> str:
    # Fail-closed (#98 E4): ein nicht-EN16931-konformes Profil (MINIMUM, BASIC-WL,
    # Tippfehler) wird NICHT still auf EN16931 gemappt — sonst trüge die XML eine
    # EN16931-Profil-ID über nicht-konformem Inhalt. Kein Codepfad darf eine als
    # E-Rechnung unzulässige XML erzeugen.
    # None/leer = Modell-Default (Spalte `zugferd_profile`: nullable=False, default
    # "EN16931") → als EN16931 behandeln. Nur ein EXPLIZIT nicht-konformes Profil
    # (MINIMUM/BASIC-WL, Tippfehler) wird abgelehnt statt still auf EN16931 gemappt.
    profile = invoice.zugferd_profile or "EN16931"
    if profile not in PROFILE_IDS:
        raise NonCompliantProfileError(
            f"ZUGFeRD-Profil {invoice.zugferd_profile!r} ist als E-Rechnung unzulässig "
            f"(§ 14 UStG verlangt mind. EN16931; MINIMUM/BASIC-WL sind nicht rechtskonform). "
            f"Erlaubt: {', '.join(sorted(PROFILE_IDS))}."
        )
    profile_id = PROFILE_IDS[profile]
    rollen = besetzung(invoice, company, invoice.customer)
    seller = rollen.verkaeufer
    customer = rollen.erwerber
    inv_cat = getattr(invoice, "tax_category", "S")

    # Einzige Stelle der Summenrechnung ist belegsummen; die gespeicherten
    # invoice.net_total/tax_total/gross_total enthalten einen Abzug bereits
    # (net_total = Steuerbasis nach Abzug) und taugen deshalb nicht als
    # Positionssumme (#147).
    abzug_betrag = getattr(invoice, "abzug_betrag", None)
    summen = belegsummen(invoice.items, abzug_betrag)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">

{exchanged_document_xml(invoice, profile_id)}

    <rsm:SupplyChainTradeTransaction>
{line_items_xml(invoice)}
{header_trade_agreement_xml(invoice, seller, customer, inv_cat)}
{delivery_xml(invoice)}
{header_trade_settlement_xml(invoice, company, summen)}
    </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""
