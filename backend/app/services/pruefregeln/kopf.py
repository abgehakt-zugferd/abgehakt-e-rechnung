"""§ 14 Abs. 4 UStG – Rechnungskopf: Nummer, Datum, Fälligkeit, Leistungsdatum.

Die Reihenfolge der Teilregeln ist Bestandteil des Vertrags (Tests pruefen
Listen): Rechnungsnummer, Ausstellungsdatum, Fälligkeit, Leistungszeitraum,
Leistungsdatum.
"""
from app.services.leistungszeit import (
    hat_leistungszeitpunkt,
    leistungszeitraum_teilweise,
    leistungszeitraum_ungueltig,
)
from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext


def pruefe_kopf(kontext: Pruefkontext) -> list[Issue]:
    """Alle Kopfbefunde, in fester Reihenfolge."""
    befunde: list[Issue] = []
    befunde.extend(_pruefe_rechnungsnummer(kontext))
    befunde.extend(_pruefe_ausstellungsdatum(kontext))
    befunde.extend(_pruefe_faelligkeit(kontext))
    befunde.extend(_pruefe_leistungszeitraum(kontext))
    befunde.extend(_pruefe_leistungsdatum(kontext))
    return befunde


def _pruefe_rechnungsnummer(kontext: Pruefkontext) -> list[Issue]:
    # § 14 Abs. 4 Nr. 4 UStG – Rechnungsnummer
    if not kontext.invoice.invoice_number:
        return [Issue("INVOICE_NUMBER_MISSING", "error", "Rechnungsnummer fehlt.", "invoice_number")]
    return []


def _pruefe_ausstellungsdatum(kontext: Pruefkontext) -> list[Issue]:
    # § 14 Abs. 4 Nr. 3 UStG – Ausstellungsdatum
    if not kontext.invoice.issue_date:
        return [Issue("ISSUE_DATE_MISSING", "error", "Ausstellungsdatum fehlt.", "issue_date")]
    return []


def _pruefe_faelligkeit(kontext: Pruefkontext) -> list[Issue]:
    # Fälligkeitsdatum logisch prüfen
    invoice = kontext.invoice
    if invoice.issue_date and invoice.due_date and invoice.due_date < invoice.issue_date:
        return [Issue("DUE_DATE_BEFORE_ISSUE", "error", "Fälligkeitsdatum liegt vor dem Ausstellungsdatum.", "due_date")]
    return []


def _pruefe_leistungszeitraum(kontext: Pruefkontext) -> list[Issue]:
    invoice = kontext.invoice
    befunde: list[Issue] = []
    if leistungszeitraum_teilweise(invoice):
        befunde.append(Issue(
            "SERVICE_PERIOD_INCOMPLETE", "error",
            "Leistungszeitraum unvollständig: von- und bis-Datum müssen beide gesetzt sein.",
            "service_period",
        ))
    if leistungszeitraum_ungueltig(invoice):
        befunde.append(Issue(
            "SERVICE_PERIOD_INVALID", "error",
            "Leistungszeitraum ungültig: das von-Datum liegt nach dem bis-Datum.",
            "service_period",
        ))
    return befunde


def _pruefe_leistungsdatum(kontext: Pruefkontext) -> list[Issue]:
    invoice = kontext.invoice
    # § 14 Abs. 4 Nr. 6 UStG – Leistungsdatum. Produktentscheid #98 E7 (2026-07-23):
    # harter Gate statt Warnung. Bei Nicht-Kleinbetragsrechnungen (über 250 €) ist der
    # Leistungszeitpunkt zwingend — fehlt er, blockiert das Finalize-Gate (400).
    # Kleinbetrag (bis 250 € einschließlich, § 33 UStDV) bleibt ausgenommen.
    #
    # Bei innergemeinschaftlicher Lieferung (Kategorie K) gilt die
    # Kleinbetragsausnahme NICHT: EN16931 verlangt über BR-IC-11 das Lieferdatum
    # (BT-72) oder einen Abrechnungszeitraum, unabhängig vom Betrag. § 33 UStDV
    # erlässt nur die nationale Pflichtangabe, die europäische Norm gilt daneben
    # weiter. Ohne diese Zeile kam der Beleg am Gate vorbei und scheiterte danach
    # an Mustang, mit einer Meldung aus dem Werkzeug statt einer aus der
    # Anwendung (#47).
    innergemeinschaftlich = kontext.steuerkategorie == "K"
    if kontext.belegart is not None and kontext.belegart.intern == "prepayment":
        return _pruefe_vorausforderung(invoice)
    if not hat_leistungszeitpunkt(invoice) and (not kontext.kleinbetrag or innergemeinschaftlich):
        return [Issue(
            "DELIVERY_DATE_MISSING", "error",
            "Zeitpunkt der Leistungserbringung fehlt. Bei einer innergemeinschaftlichen "
            "Lieferung ist er unabhängig vom Rechnungsbetrag zwingend (EN16931, BR-IC-11); "
            "die Kleinbetragsregelung des § 33 UStDV gilt dafür nicht."
            if innergemeinschaftlich else
            "Zeitpunkt der Leistungserbringung fehlt (§ 14 Abs. 4 Nr. 6 UStG) — bei Rechnungen über 250 € zwingend erforderlich.",
            "delivery_date"
        )]
    return []


def _pruefe_vorausforderung(invoice) -> list[Issue]:
    # Produktbegrenzung des ersten 386-Schnitts (docs/specs/vorabrechnung.md):
    # nur die noch nicht bezahlte Vorausforderung mit bekanntem geplantem
    # Leistungszeitraum. Das ist STRENGER als EN16931 — die Norm kennt diese
    # Pflicht nicht — und ist eine Produktentscheidung, keine Normpflicht.
    # Ein noch nicht eingetretenes Ereignis darf nicht als tatsaechliche
    # Lieferung ausgegeben werden; das Rechnungsdatum wird nie als Lieferung
    # eingesetzt. Teilzeitraum und falsche Reihenfolge meldet
    # _pruefe_leistungszeitraum oben (SERVICE_PERIOD_INCOMPLETE / _INVALID).
    befunde: list[Issue] = []
    if invoice.delivery_date:
        befunde.append(Issue(
            "PREPAYMENT_ACTUAL_DELIVERY", "error",
            "Anzahlungsrechnung mit tatsaechlichem Leistungsdatum: dieser Schnitt "
            "bildet nur die noch nicht bezahlte Vorausforderung mit geplantem "
            "Zeitraum ab. Leistungsdatum leeren und stattdessen den "
            "voraussichtlichen Leistungszeitraum (von und bis) setzen.",
            "delivery_date",
        ))
    if not invoice.service_period_start and not invoice.service_period_end:
        befunde.append(Issue(
            "PREPAYMENT_PERIOD_REQUIRED", "error",
            "Anzahlungsrechnung braucht den voraussichtlichen Leistungszeitraum "
            "(von und bis). Er ersetzt hier das Leistungsdatum, unabhaengig "
            "vom Rechnungsbetrag.",
            "service_period",
        ))
    return befunde
