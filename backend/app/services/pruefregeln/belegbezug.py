"""Konsistenz Rechnungstyp ↔ Originalbezug sowie Gutschrift-Spiegel."""
from app.services.belegart import TYPE_CODE_MAP
from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext


def pruefe_belegbezug(kontext: Pruefkontext) -> list[Issue]:
    """Alle Befunde zu Belegart und Originalbezug, in fester Reihenfolge."""
    befunde: list[Issue] = []
    befunde.extend(_pruefe_originalbezug(kontext))
    befunde.extend(_pruefe_gutschrift_spiegel(kontext))
    return befunde


def _pruefe_originalbezug(kontext: Pruefkontext) -> list[Issue]:
    invoice = kontext.invoice
    # Konsistenz Rechnungstyp ↔ Originalbezug (ROADMAP Punkt 3).
    # invoice_type muss bekannt sein; Folgebelege (Gutschrift/Storno/Korrektur/
    # Gutschriftverfahren) verlangen eine Originalreferenz, eine eigenstaendige
    # Rechnung (380 und die Anzahlungsrechnung 386) darf keine haben.
    original_ref = getattr(invoice, "original_invoice_id", None)
    if kontext.belegart is None:
        return [Issue(
            "INVOICE_TYPE_INVALID", "error",
            f"Unbekannter Rechnungstyp '{kontext.rechnungstyp}'. "
            f"Erlaubt: {', '.join(str(t) for t in TYPE_CODE_MAP if t)}.",
            "invoice_type"
        )]
    requires_reference = kontext.belegart.braucht_original
    fehler: list[Issue] = []
    if requires_reference and not original_ref:
        fehler.append(Issue(
            "ORIGINAL_INVOICE_REQUIRED", "error",
            "Gutschrift/Storno/Korrektur muss die Originalrechnung referenzieren "
            "(original_invoice_id fehlt).",
            "original_invoice_id"
        ))
    if not requires_reference and original_ref:
        fehler.append(Issue(
            "ORIGINAL_INVOICE_NOT_ALLOWED", "error",
            "Eine Standardrechnung darf keine Originalrechnung referenzieren.",
            "original_invoice_id"
        ))
    return fehler


def _pruefe_gutschrift_spiegel(kontext: Pruefkontext) -> list[Issue]:
    invoice = kontext.invoice
    # Eine Gutschrift spiegelt ihr Original betragsgleich (#8). `build_storno`
    # kopiert die Summen 1:1, und die Bearbeitungsseite ist für Gutschriften
    # gesperrt — diese Prüfung ist die zweite Schicht davor, so wie die Wächter in
    # der Anwendung und die Auslöser in der Datenbank zwei Schichten derselben
    # Zusage sind. Sie steht hier, weil das Finalisieren fail-closed ist: was den
    # Validator passiert, wandert unwiderruflich ins Archiv.
    #
    # OHNE Toleranz, anders als bei den Positionssummen. Dort wird gerechnet und
    # gerundet, hier wird kopiert; jede Abweichung ist eine Eingabe, keine
    # Rundung. Eine Toleranz ließe genau die Tür offen, die diese Regel schließt.
    #
    # `original_invoice` fehlt bei Testattrappen und bei einer noch nicht
    # geladenen Beziehung; dann greift die Regel nicht. Die Referenz als solche
    # verlangt bereits ORIGINAL_INVOICE_REQUIRED in _pruefe_originalbezug oben.
    if kontext.belegart is None or kontext.belegart.intern not in {
        "credit_note", "self_billing_storno",
    }:
        return []
    original = getattr(invoice, "original_invoice", None)
    fehler: list[Issue] = []
    if original is not None:
        for feld, bezeichnung in (("net_total", "Nettobetrag"),
                                  ("tax_total", "Steuerbetrag"),
                                  ("gross_total", "Bruttobetrag")):
            if getattr(invoice, feld, None) != getattr(original, feld, None):
                fehler.append(Issue(
                    "STORNO_AMOUNT_MISMATCH", "error",
                    f"{bezeichnung} der Gutschrift weicht von der Originalrechnung "
                    f"{original.invoice_number} ab "
                    f"({getattr(invoice, feld, None)} statt {getattr(original, feld, None)}). "
                    "Eine Stornierung hebt den Beleg vollständig auf; eine "
                    "abweichende Summe wäre eine Teilkorrektur und braucht einen "
                    "eigenen Beleg.",
                    feld
                ))
    return fehler
