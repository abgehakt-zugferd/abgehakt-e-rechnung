"""§ 14 Abs. 4 Nr. 1 UStG – Leistungsempfänger."""
from decimal import Decimal

from app.services.kunde_zuordenbar import Zuordnung, meldung_fuer, zuordnung_von
from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext
from app.services.pruefregeln.ust_id import ust_id_befunde
from app.services.steuerkategorie_land import kategorie_passt_zum_land


def pruefe_leistungsempfaenger(kontext: Pruefkontext) -> list[Issue]:
    invoice = kontext.invoice
    gross = invoice.gross_total
    tax_category = kontext.steuerkategorie
    customer = invoice.customer
    if not customer:
        return [Issue("BUYER_MISSING", "error", "Kein Kunde zugeordnet.", "customer_id")]
    # Zuordnung nur am Entwurf (#173): /pruefen laeuft fuer jeden Status und
    # wuerde sonst gestellte Belege nach Spaet-Deaktivierung ungueltig speichern.
    # Status steht am Beleg (Pruefkontext.invoice); Finalisieren allein reicht
    # nicht, weil Entwuerfe auch ueber /pruefen und speichern geprueft werden.
    if getattr(invoice, "status", None) == "draft":
        lage = zuordnung_von(customer)
        if lage is not Zuordnung.ZUORDENBAR:
            return [Issue(
                "BUYER_NOT_ASSIGNABLE", "error", meldung_fuer(lage), "customer_id",
            )]
    befunde: list[Issue] = []
    if not customer.name or not customer.name.strip():
        befunde.append(Issue("BUYER_NAME_MISSING", "error", "Name des Kunden fehlt.", "customer.name"))
    if not customer.address_line1 or not customer.zip_code or not customer.city:
        befunde.append(Issue("BUYER_ADDRESS_MISSING", "error", "Vollständige Adresse des Kunden fehlt.", "customer.address"))

    # Hoher Rechnungsbetrag ohne USt-IdNr. des Empfängers → Hinweis (kein harter Fehler).
    # § 14a Abs. 1 UStG verlangt die USt-IdNr. des Empfängers nur bei Leistungen i.S.d.
    # § 3a Abs. 2 UStG (grenzüberschreitend/Reverse Charge, Kategorie AE) bzw.
    # § 14a Abs. 3 UStG (innergemeinschaftliche Lieferung, Kategorie K),
    # nicht generell bei inländischen B2B-Rechnungen über 10.000 €. Eine inländische Rechnung
    # über 10.000 € an einen Kunden ohne USt-IdNr. ist zulässig und darf nicht blockiert werden.
    if gross > Decimal("10000") and not customer.vat_id:
        befunde.append(Issue(
            "HIGH_VALUE_NO_BUYER_VAT_ID", "warning",
            f"Rechnungsbetrag {gross:.2f} € übersteigt 10.000 €. "
            f"Bei B2B-Geschäften wird die Angabe der USt-IdNr. des Leistungsempfängers empfohlen.",
            "customer.vat_id"
        ))
    # Steuerkategorie gegen das Land des Kunden (#145): Warnung, kein harter
    # Fehler, weil Ausnahmen im Einzelfall zulässig bleiben. Die Regeln und
    # Warntexte stehen im Modul steuerkategorie_land.py.
    hinweis = kategorie_passt_zum_land(tax_category, customer.country)
    if hinweis:
        befunde.append(Issue(
            "TAX_CATEGORY_COUNTRY_MISMATCH", "warning", hinweis, "tax_category"
        ))
    if customer.vat_id:
        befunde.extend(ust_id_befunde(customer, prefix="BUYER", field="customer.vat_id"))
    return befunde
