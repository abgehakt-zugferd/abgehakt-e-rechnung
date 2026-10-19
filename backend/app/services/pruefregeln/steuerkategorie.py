"""MwSt.-Kategorie (§ 14 UStG, EN16931)."""
from decimal import Decimal

from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext

# "E" ist seit #152 gültig und meint hier genau einen Fall: den Kleinunternehmer
# nach § 19 UStG. Der Befreiungsgrund in EXEMPTION_REASONS nennt § 19 ausdrücklich,
# und wer eine andere Befreiung nach § 4 UStG braucht (Heilbehandlung, Versicherung),
# bekäme mit diesem Text eine falsche Begründung auf den Beleg. Solche Fälle daher
# erst aufnehmen, wenn der Grund pro Rechnung wählbar ist — nicht heimlich mitnutzen.
#
# Weiterhin NICHT gültig: "G" (Ausfuhr Drittland). Inländische 0 %-Umsätze bleiben
# "Z" (steuerpflichtig zum Satz null), das ist etwas anderes als steuerbefreit.
VALID_TAX_CATEGORIES = {"S", "AE", "K", "O", "E"}
# Kategorien, in denen keine Steuer ausgewiesen werden darf. Bei "E" ist das keine
# Formalie: ein Kleinunternehmer, der Umsatzsteuer ausweist, schuldet sie nach
# § 14c Abs. 2 UStG, obwohl er sie gar nicht erheben durfte.
STEUERFREIE_KATEGORIEN = {"AE", "K", "O", "E"}


def pruefe_steuerkategorie(kontext: Pruefkontext) -> list[Issue]:
    invoice = kontext.invoice
    customer = invoice.customer
    tax_category = kontext.steuerkategorie
    # MwSt.-Kategorie prüfen
    if tax_category not in VALID_TAX_CATEGORIES:
        return [Issue(
            "TAX_CATEGORY_INVALID", "error",
            "Unbekannte MwSt.-Kategorie.", "tax_category"
        )]
    if tax_category not in STEUERFREIE_KATEGORIEN:
        return []
    fehler: list[Issue] = []
    if invoice.items and any(item.tax_rate > Decimal("0") for item in invoice.items):
        meldung = (
            "Als Kleinunternehmer nach § 19 UStG dürfen Sie keine Umsatzsteuer "
            "ausweisen. Ausgewiesene Steuer schulden Sie nach § 14c Abs. 2 UStG "
            "trotzdem. Steuersatz auf 0 % setzen."
            if tax_category == "E" else
            "Bei Reverse Charge / steuerfreien Lieferungen muss der Steuersatz 0 % betragen."
        )
        fehler.append(Issue(
            "TAX_CATEGORY_RATE_MISMATCH", "error", meldung, "tax_category"
        ))
    if tax_category in {"AE", "K"} and customer and not customer.vat_id:
        fehler.append(Issue(
            "BUYER_VAT_ID_REQUIRED", "error",
            "Für Reverse Charge und innergemeinschaftliche Lieferungen ist die USt-IdNr. des Käufers Pflicht.",
            "customer.vat_id"
        ))
    return fehler
