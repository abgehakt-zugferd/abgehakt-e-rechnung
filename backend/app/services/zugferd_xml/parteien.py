"""Verkaeufer, Kaeufer, Kontakt, Adressen und Steuer-IDs (HeaderTradeAgreement)."""
from app.models.invoice import Invoice
from app.services.adresse import bereinige_adresszeile2
from app.services.belegrollen import Partei
from app.services.belegsprache import resolve_belegsprache
from app.services.pflichtangaben import pflichtangaben

from app.services.zugferd_xml.format import esc


def seller_id_xml(company: Partei, tax_category: str = "S") -> str:
    """BT-29, die Verkäufer-Kennung. Steht als erstes Kind von `SellerTradeParty`
    (die CII-Sequenz ist geordnet: ID, GlobalID, Name, …).

    Warum es sie gibt: EN 16931 verlangt über `BR-CO-26` eine Verkäufer-Kennung
    (BT-29), eine Registernummer (BT-30) ODER die USt-IdNr. (BT-31). Die
    Steuernummer geht als BT-32 ins Dokument und zählt dafür NICHT. Die Einrichtung
    lässt aber ausdrücklich „Steuernummer oder USt-IdNr." zu, weil § 14 UStG das so
    vorsieht. Ohne diese Kennung konnte deshalb jemand ohne USt-IdNr. alles richtig
    ausfüllen und trotzdem keine einzige Rechnung finalisieren (Abnahme 2026-08-09).

    Nur wenn die USt-IdNr. fehlt: liegt sie vor, ist `BR-CO-26` schon erfüllt und
    eine zweite Nennung derselben Nummer wäre Beiwerk. Offengelegt wird nichts Neues,
    die Steuernummer steht nach § 14 ohnehin auf jeder Rechnung.

    Bei Kategorie O entfällt BT-31 (BR-O-02); dann muss BT-29 die Steuernummer
    tragen, auch wenn eine USt-IdNr. in der Einrichtung hinterlegt ist.
    """
    if company.vat_id and tax_category != "O":
        return ""
    if not company.tax_number:
        return ""
    return f"""
                <ram:ID>{esc(company.tax_number)}</ram:ID>"""


def seller_legal_xml(company: Partei, invoice: Invoice) -> str:
    """BT-33 und BT-30: Pflichtangaben des Geschäftsbriefs (services/pflichtangaben.py).

    CII-Reihenfolge: Name, Description, SpecifiedLegalOrganization, DefinedTradeContact.
    Dieselben Zeilen wie im PDF-Fuß, damit beide Teile des Belegs dasselbe sagen.
    """
    sprache = resolve_belegsprache(getattr(invoice, "document_language", None) or "de")
    angaben = pflichtangaben(company, sprache)
    teile = []
    if angaben.zeilen:
        teile.append(f"""
                <ram:Description>{esc(chr(10).join(angaben.zeilen))}</ram:Description>""")
    if angaben.registernummer:
        teile.append(f"""
                <ram:SpecifiedLegalOrganization>
                    <ram:ID>{esc(angaben.registernummer)}</ram:ID>
                </ram:SpecifiedLegalOrganization>""")
    return "".join(teile)


def seller_contact_xml(company: Partei) -> str:
    """BG-6, der Ansprechpartner des Verkäufers (BT-41/42/43).

    Steht in der CII-Sequenz zwischen `SpecifiedLegalOrganization` und
    `PostalTradeAddress` — an anderer Stelle ist es ein Schemafehler.

    Bei der Firma tritt ohne eigens gepflegten Namen der Firmenname an die Stelle:
    BT-41 ist der Kontaktpunkt, nicht zwingend eine natürliche Person, und ein leeres Element
    wäre schema-ungültig. Telefon und Mail entfallen einzeln, wenn sie fehlen.
    """
    name = company.kontakt_name
    if not name:
        return ""
    teile = [f"""
                    <ram:PersonName>{esc(name)}</ram:PersonName>"""]
    if company.phone:
        teile.append(f"""
                    <ram:TelephoneUniversalCommunication>
                        <ram:CompleteNumber>{esc(company.phone)}</ram:CompleteNumber>
                    </ram:TelephoneUniversalCommunication>""")
    if company.email:
        teile.append(f"""
                    <ram:EmailURIUniversalCommunication>
                        <ram:URIID>{esc(company.email)}</ram:URIID>
                    </ram:EmailURIUniversalCommunication>""")
    return f"""
                <ram:DefinedTradeContact>{''.join(teile)}
                </ram:DefinedTradeContact>"""


def electronic_address_xml(email) -> str:
    """BT-34 (Verkäufer) bzw. BT-49 (Käufer): die elektronische Adresse, an die
    eine E-Rechnung maschinell zugestellt werden könnte.

    `schemeID="EM"` ist der EAS-Code für eine Mailadresse. Ohne Adresse entfällt
    der ganze Block: ein leeres `URIID` wäre ein Schemafehler, und die Angabe ist
    nach EN 16931 optional.

    Steht in der CII-Sequenz NACH `PostalTradeAddress` und VOR
    `SpecifiedTaxRegistration`.
    """
    if not email:
        return ""
    return f"""
                <ram:URIUniversalCommunication>
                    <ram:URIID schemeID="EM">{esc(email)}</ram:URIID>
                </ram:URIUniversalCommunication>"""


def buyer_id_xml(customer) -> str:
    """BT-46, die Kundennummer. Erstes Kind von `BuyerTradeParty` (CII-Sequenz
    ID, GlobalID, Name). Das PDF druckt sie im Kopf; ohne sie hier sagten PDF und
    XML Verschiedenes. Ohne Nummer kein Element, ein leeres wäre schema-ungültig.
    """
    nummer = (getattr(customer, "customer_number", None) or "").strip() if customer else ""
    if not nummer:
        return ""
    return f"""
                <ram:ID>{esc(nummer)}</ram:ID>"""


def buyer_reference_xml(invoice: Invoice) -> str:
    """BT-10, die Referenz des Käufers. Erstes Kind von
    `ApplicableHeaderTradeAgreement`, also VOR `SellerTradeParty`."""
    referenz = (getattr(invoice, "buyer_reference", None) or "").strip()
    if not referenz:
        return ""
    return f"""
            <ram:BuyerReference>{esc(referenz)}</ram:BuyerReference>"""


def buyer_order_reference_xml(invoice: Invoice) -> str:
    """BT-13, Bestellnummer des Kunden (#101).

    CII-Position in `ApplicableHeaderTradeAgreement` laut UN/CEFACT
    `HeaderTradeAgreementType` / ZUGFeRD Technischer Anhang Profil EN16931:
    BuyerReference, SellerTradeParty, BuyerTradeParty,
    SellerTaxRepresentativeTradeParty, SellerOrderReferencedDocument,
    **BuyerOrderReferencedDocument**, ContractReferencedDocument, …
    Also NACH `BuyerTradeParty`. Ohne Wert kein Element (leeres Element wäre
    ein Schemafehler und schlimmer als keines).
    """
    bestellnummer = (getattr(invoice, "buyer_order_reference", None) or "").strip()
    if not bestellnummer:
        return ""
    return f"""
            <ram:BuyerOrderReferencedDocument>
                <ram:IssuerAssignedID>{esc(bestellnummer)}</ram:IssuerAssignedID>
            </ram:BuyerOrderReferencedDocument>"""


def seller_tax_xml(company: Partei, tax_category: str) -> str:
    parts = []
    if company.tax_number:
        parts.append(f"""
                <ram:SpecifiedTaxRegistration>
                    <ram:ID schemeID="FC">{esc(company.tax_number)}</ram:ID>
                </ram:SpecifiedTaxRegistration>""")
    # BR-O-02: bei Kategorie O keine Verkaeufer-USt-IdNr. (BT-31).
    if company.vat_id and tax_category != "O":
        parts.append(f"""
                <ram:SpecifiedTaxRegistration>
                    <ram:ID schemeID="VA">{esc(company.vat_id)}</ram:ID>
                </ram:SpecifiedTaxRegistration>""")
    return "\n".join(parts)


def buyer_vat_xml(customer, tax_category: str) -> str:
    if tax_category == "O":
        return ""
    if customer and customer.vat_id:
        return f"""
                <ram:SpecifiedTaxRegistration>
                    <ram:ID schemeID="VA">{esc(customer.vat_id)}</ram:ID>
                </ram:SpecifiedTaxRegistration>"""
    return ""


def _addr2_xml(name, address_line2) -> str:
    line2 = bereinige_adresszeile2(name, address_line2)
    if not line2:
        return ""
    return f"\n                    <ram:LineTwo>{esc(line2)}</ram:LineTwo>"


def seller_trade_party_xml(seller: Partei, invoice: Invoice, inv_cat: str) -> str:
    addr2 = _addr2_xml(seller.name, seller.address_line2)
    return f"""            <ram:SellerTradeParty>{seller_id_xml(seller, inv_cat)}
                <ram:Name>{esc(seller.name)}</ram:Name>{seller_legal_xml(seller, invoice)}{seller_contact_xml(seller)}
                <ram:PostalTradeAddress>
                    <ram:PostcodeCode>{esc(seller.zip_code)}</ram:PostcodeCode>
                    <ram:LineOne>{esc(seller.address_line1)}</ram:LineOne>{addr2}
                    <ram:CityName>{esc(seller.city)}</ram:CityName>
                    <ram:CountryID>{esc(seller.country)}</ram:CountryID>
                </ram:PostalTradeAddress>{electronic_address_xml(seller.email)}{seller_tax_xml(seller, inv_cat)}
            </ram:SellerTradeParty>"""


def buyer_trade_party_xml(customer, inv_cat: str) -> str:
    addr2 = ""
    if customer:
        addr2 = _addr2_xml(customer.name, customer.address_line2)
    return f"""            <ram:BuyerTradeParty>{buyer_id_xml(customer)}
                <ram:Name>{esc(customer.name if customer else "")}</ram:Name>
                <ram:PostalTradeAddress>
                    <ram:PostcodeCode>{esc(customer.zip_code if customer else "")}</ram:PostcodeCode>
                    <ram:LineOne>{esc(customer.address_line1 if customer else "")}</ram:LineOne>{addr2}
                    <ram:CityName>{esc(customer.city if customer else "")}</ram:CityName>
                    <ram:CountryID>{esc(customer.country if customer else "DE")}</ram:CountryID>
                </ram:PostalTradeAddress>{electronic_address_xml(customer.email if customer else None)}{buyer_vat_xml(customer, inv_cat)}
            </ram:BuyerTradeParty>"""


def header_trade_agreement_xml(invoice: Invoice, seller: Partei, customer, inv_cat: str) -> str:
    return f"""        <ram:ApplicableHeaderTradeAgreement>{buyer_reference_xml(invoice)}
{seller_trade_party_xml(seller, invoice, inv_cat)}
{buyer_trade_party_xml(customer, inv_cat)}{buyer_order_reference_xml(invoice)}
        </ram:ApplicableHeaderTradeAgreement>"""
