"""Fachlogik fuer Rechnungstitel, Zahlfluss und Positionszeilen."""

from __future__ import annotations

from decimal import Decimal
from xml.sax.saxutils import escape

from reportlab.platypus import Paragraph

from app.models.invoice import Invoice
from app.services.auftragszahlung import ohne_ueberweisungsaufforderung
from app.services.belegart import belegart, zahlung_an_kunde
from app.services.belegsprache import Belegdarstellung, darstellung, resolve_belegsprache
from app.services.zugferd_xml import EXEMPTION_REASONS

from .layout import description_markup, item_style

# PDF-Steuerhinweise kommen aus Belegdarstellung (sprachabhaengig fuer E/K/O;
# AE immer zweisprachig). Ob eine Steuerzeile angezeigt wird, richtet sich weiter
# nach den Kategorien in EXEMPTION_REASONS (XML-Tabelle), nicht nach dem Wortlaut.
TAX_NOTICE_KATEGORIEN = frozenset(EXEMPTION_REASONS)


# Welche Belegarten an den Kunden zahlen (und damit ohne eigenen Bankblock
# auskommen), entscheidet belegart.zahlung_an_kunde ueber die aufgeloeste
# Belegart — hier nur der Leser.
def ist_gutschrift(invoice) -> bool:
    return zahlung_an_kunde(getattr(invoice, "invoice_type", None))


def belegdarstellung(invoice) -> Belegdarstellung:
    """Sprache der Rechnung → Darstellung. Unbekannt = harter Fehler vor Ausgabe."""
    roh = getattr(invoice, "document_language", None)
    if roh is None:
        roh = "de"
    return darstellung(resolve_belegsprache(roh))


def zahlung_an_kunde_beleg(invoice) -> bool:
    """Gutschrift: Überweisung an den Kunden (nicht an die Firma)."""
    return ist_gutschrift(invoice)


def zahlungs_empfaenger(invoice, company):
    """(Name, IBAN, BIC, Bankname) für Anzeige und EPC-QR, oder None."""
    if ohne_ueberweisungsaufforderung(invoice):
        return None
    customer = invoice.customer
    if zahlung_an_kunde_beleg(invoice):
        if not customer or not customer.bank_iban:
            return None
        return (customer.name, customer.bank_iban, customer.bank_bic, customer.bank_name)
    if company.bank_iban:
        return (company.name, company.bank_iban, company.bank_bic, company.bank_name)
    return None


def document_title(invoice) -> str:
    """Sichtbarer Belegtitel aus Belegdarstellung zur Belegsprache.
    Unbekannte Typen werfen UnknownInvoiceTypeError (fail-closed, wie XML)."""
    art = belegart(getattr(invoice, "invoice_type", None))
    return belegdarstellung(invoice).titel(art.intern)


def pct(v: Decimal) -> str:
    pct_wert = v.quantize(Decimal("0"))
    return f"{pct_wert} %"


def zeigt_steuer(invoice: Invoice) -> bool:
    """Ob der Beleg überhaupt Umsatzsteuer ausweist.

    Maßstab sind die Kategorien in EXEMPTION_REASONS: wo ein Befreiungsgrund
    steht, ist eine Steuerzeile ein Widerspruch — die Rechnung sagte oben
    „hier wird keine Umsatzsteuer ausgewiesen" und rechnete unten „zzgl. 0 %
    MwSt. — 0,00 €" vor.

    Es geht dabei nicht um § 14c: ein Betrag von null ist kein unrichtiger
    Steuerausweis. Es geht um Verständlichkeit, und bei AE um mehr als das — der
    Empfänger einer Reverse-Charge-Rechnung muss erkennen, dass ER die Steuer
    schuldet, und keine Zeile lesen, die einen Steuervorgang mit dem Ergebnis null
    nahelegt.
    """
    return getattr(invoice, "tax_category", "S") not in TAX_NOTICE_KATEGORIEN


def beschreibung_mit_angaben(item, d: Belegdarstellung, waehrung: str = "EUR") -> str:
    """Beschreibung plus optionale Zusatzangaben der Position als kleine Zeile darunter."""
    markup = description_markup(item.description)
    nummer = (getattr(item, "artikelnummer", None) or "").strip()
    if nummer:
        markup += f'<br/><font size="7">{escape(d.label_artikelnummer)} {escape(nummer)}</font>'
    von = getattr(item, "leistung_von", None)
    bis = getattr(item, "leistung_bis", None)
    if von and bis:
        zeitraum = f"{d.label_leistungszeitraum} {d.format_datum(von)} – {d.format_datum(bis)}"
        markup += f'<br/><font size="7">{escape(zeitraum)}</font>'
    basis = getattr(item, "basis_netto", None)
    satz = getattr(item, "satz", None)
    if basis is not None and satz is not None:
        # Beteiligungssatz gehoert zur Herleitung, nie zur Umsatzsteuerspalte.
        markup += f'<br/><font size="7">{escape(d.herleitungszeile(basis, satz, waehrung))}</font>'
    return markup


def gruppen_runs(items) -> list:
    """Zerlegt die Positionen in zusammenhängende Laeufe gleicher Gruppe.

    Der Validator (und der Leser) erzwingen, dass Positionen derselben Gruppe
    aufeinanderfolgen; hier wird das nicht noch einmal geprueft, sondern nur
    gezaehlt: zwei getrennte Laeufe desselben Gruppentextes wuerden zwei
    Zwischensummen desselben Namens drucken.
    """
    runs = []
    for item in items:
        gruppe = getattr(item, "gruppe", None) or None
        if runs and runs[-1][0] == gruppe:
            runs[-1][1].append(item)
        else:
            runs.append((gruppe, [item]))
    return runs


def build_item_rows(invoice: Invoice, d: Belegdarstellung) -> list[list]:
    """Zeilen für die Positionstabelle. Die Beschreibung wird als Paragraph
    ausgegeben, damit sie in ihrer Spalte umbricht statt überzulaufen."""
    desc_style = item_style()
    mit_steuer = zeigt_steuer(invoice)
    kopf = [d.label_pos, d.label_beschreibung, d.label_menge, d.label_einheit, d.label_einzelpreis]
    if mit_steuer:
        kopf.append(d.label_mwst)
    kopf.append(d.label_betrag)
    rows = [kopf]
    waehrung = getattr(invoice, "currency", "EUR") or "EUR"
    for gruppe, run_items in gruppen_runs(invoice.items):
        rows.extend(_gruppenzeilen(gruppe, run_items, d, waehrung, len(kopf), mit_steuer, desc_style))
    return rows


def _gruppenzeilen(gruppe, run_items, d, waehrung, spalten, mit_steuer, desc_style):
    rows = []
    if gruppe:
        # Ueberschrift vor der ersten Position der Gruppe; der Text steht
        # in der Beschreibungsspalte, die als einzige umbricht — ein langer
        # Gruppentext laeuft so nicht aus der Tabelle.
        rows.append(["", gruppe] + [""] * (spalten - 2))
    for item in run_items:
        rows.append(_positionszeile(item, d, waehrung, mit_steuer, desc_style))
    if gruppe:
        # Reine Addition der Positionsnetto, keine Rundung, kein Steueranteil:
        # Die Zwischensumme gliedert, sie ist keine eigene Postenart. Das
        # Label steht in der Belegsprache (belegsprache/).
        summe = sum((item.net_amount for item in run_items), Decimal("0"))
        rows.append(["", f"{d.label_zwischensumme} {gruppe}"] + [""] * (spalten - 3) + [d.format_betrag(summe, waehrung)])
    return rows


def _positionszeile(item, d, waehrung, mit_steuer, desc_style):
    zeile = [
        str(item.position),
        Paragraph(beschreibung_mit_angaben(item, d, waehrung), desc_style),
        # NICHT `str(x.normalize())`: das kippt bei durch zehn teilbaren
        # Mengen in die Exponentialform — 120 Stunden stünden als "1.2E+2"
        # auf der Rechnung an den Kunden.
        d.format_menge(item.quantity),
        item.unit,
        d.format_betrag(item.unit_price, waehrung),
    ]
    if mit_steuer:
        zeile.append(pct(item.tax_rate))
    zeile.append(d.format_betrag(item.net_amount, waehrung))
    return zeile
