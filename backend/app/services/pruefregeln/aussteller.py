"""§ 14 Abs. 4 UStG – Pflichtangaben des Leistungserbringers.

Die Reihenfolge der vier Teilregeln ist Bestandteil des Vertrags: Anschrift,
Steuerkennung, Geschäftsbrief-Pflichtangaben, VIES-Pruefstand.
"""
from app.services.belegrollen import besetzung
from app.services.pflichtangaben import pflichtangaben
from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext
from app.services.pruefregeln.ust_id import ust_id_befunde


def pruefe_aussteller(kontext: Pruefkontext) -> list[Issue]:
    """Alle Befunde zum Leistungserbringer, in fester Reihenfolge."""
    befunde: list[Issue] = []
    befunde.extend(_pruefe_anschrift(kontext))
    befunde.extend(_pruefe_steuerkennung(kontext))
    befunde.extend(_pruefe_pflichtangaben(kontext))
    befunde.extend(_pruefe_ust_id(kontext))
    return befunde


def _pruefe_anschrift(kontext: Pruefkontext) -> list[Issue]:
    company = kontext.company
    befunde: list[Issue] = []
    if not company.name or not company.name.strip():
        befunde.append(Issue("SELLER_NAME_MISSING", "error", "Firmenname fehlt in den Einstellungen.", "company.name"))
    if not company.address_line1 or not company.zip_code or not company.city:
        befunde.append(Issue("SELLER_ADDRESS_MISSING", "error", "Vollständige Adresse des Leistungserbringers fehlt.", "company.address"))
    return befunde


def _pruefe_steuerkennung(kontext: Pruefkontext) -> list[Issue]:
    # Die Steuerkennung gehört dem Leistenden, auch wenn der Erwerber den
    # Beleg ausstellt. Unbekannte Typen bekommen in belegbezug.py ihren
    # eigenen Befund.
    if kontext.belegart is None:
        return []
    rollen = besetzung(kontext.invoice, kontext.company, kontext.invoice.customer)
    seller = rollen.verkaeufer
    seller_field = "company" if rollen.verkaeufer_ist_firma else "customer"
    tax_category = kontext.steuerkategorie
    if not seller.steuernummer and not seller.ust_id:
        code = ("SELLER_TAX_ID_MISSING" if rollen.verkaeufer_ist_firma
                else "SELF_BILLING_SELLER_TAX_ID_MISSING")
        return [Issue(
            code, "error",
            "Steuernummer oder USt-IdNr. des Leistungserbringers fehlt "
            "(§ 14 Abs. 4 Nr. 2 UStG).",
            f"{seller_field}.tax",
        )]
    if tax_category == "O" and not seller.steuernummer:
        return [Issue(
            "SELLER_TAX_NUMBER_REQUIRED_FOR_O", "error",
            "Bei Kategorie O (nicht im Inland steuerbar, § 3a Abs. 2 UStG) muss die "
            "Steuernummer beim Leistungserbringer hinterlegt sein (EN16931 BR-CO-26). "
            "Die USt-IdNr. allein genügt hier nicht.",
            f"{seller_field}.tax_number",
        )]
    if tax_category == "AE" and not seller.ust_id:
        return [Issue(
            "SELLER_VAT_ID_REQUIRED", "error",
            "Bei Reverse Charge (Kategorie AE) muss die USt-IdNr. "
            "beim Leistungserbringer hinterlegt sein (§ 14a Abs. 1 Satz 3 UStG). "
            "Die Steuernummer allein genügt hier nicht.",
            f"{seller_field}.vat_id",
        )]
    if tax_category == "K" and not seller.ust_id:
        return [Issue(
            "SELLER_VAT_ID_REQUIRED", "error",
            "Bei innergemeinschaftlicher Lieferung (Kategorie K) muss die USt-IdNr. "
            "beim Leistungserbringer hinterlegt sein "
            "(§ 14a Abs. 3 Satz 2 UStG). Die Steuernummer allein genügt hier nicht.",
            f"{seller_field}.vat_id",
        )]
    return []


def _pruefe_pflichtangaben(kontext: Pruefkontext) -> list[Issue]:
    angaben = pflichtangaben(kontext.company)
    if angaben.fehlend:
        return [Issue(
            "SELLER_PFLICHTANGABEN_MISSING", "error",
            f"Pflichtangaben für Geschäftsbriefe fehlen in den Einstellungen: {angaben.luecke()}.",
            f"company.{angaben.fehlend[0]}",
        )]
    return []


def _pruefe_ust_id(kontext: Pruefkontext) -> list[Issue]:
    if kontext.company.vat_id:
        return ust_id_befunde(kontext.company, prefix="SELLER", field="company.vat_id")
    return []
