"""Abzug auf Belegebene (BG-20) und Gesamtbeträge.

Der Summenvergleich hängt am Abzug-Befund desselben Durchlaufs: liegt ein
ABZUG-Fehler vor, entfaellt er. Diese Abhaengigkeit wird zwischen den beiden
Teilregeln ausdruecklich weitergereicht, nicht versteckt.
"""
from decimal import Decimal

from app.services.belegsummen import belegsummen
from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext
from app.services.pruefregeln.steuerkategorie import KEIN_STEUERAUSWEIS


def pruefe_abzug_summen(kontext: Pruefkontext) -> list[Issue]:
    """Alle Befunde zu Abzug (BG-20) und Gesamtbetraegen, in fester Reihenfolge."""
    fehler, abzug_fehler = _pruefe_abzug(kontext)
    return fehler + _pruefe_gesamtsummen(kontext, abzug_fehler)


def _pruefe_abzug(kontext: Pruefkontext) -> tuple[list[Issue], bool]:
    """Abzugsbefunde und das Flag, ob ein ABZUG-Fehler vorliegt."""
    invoice = kontext.invoice
    art = kontext.belegart
    abzug_betrag = kontext.abzug_betrag
    abzug_grund = kontext.abzug_grund
    # Abzug auf Belegebene (BG-20). Betrag und Grund sind ein Paar:
    # EN 16931 BR-33 verlangt den Grund zum Abzug.
    fehler: list[Issue] = []
    abzug_fehler = False
    if abzug_betrag is not None or abzug_grund is not None:
        if (abzug_betrag is None) != (abzug_grund is None):
            fehler.append(Issue(
                "ABZUG_UNVOLLSTAENDIG", "error",
                "Abzug unvollständig: Betrag und Grund müssen zusammen gesetzt werden "
                "(EN 16931 BR-33 verlangt einen Grund zum Abzug).",
                "abzug_betrag",
            ))
            abzug_fehler = True
        elif abzug_betrag <= Decimal("0"):
            fehler.append(Issue(
                "ABZUG_NICHT_POSITIV", "error",
                "Der Abzug muss größer als 0,00 € sein.",
                "abzug_betrag",
            ))
            abzug_fehler = True
        elif art is not None and art.intern in {"self_billing", "prepayment"}:
            fehler.append(Issue(
                "ABZUG_BELEGART", "error",
                "Bei Anzahlungsrechnung (386) und Honorargutschrift (389) ist ein "
                "Abzug auf Belegebene unzulässig.",
                "abzug_betrag",
            ))
            abzug_fehler = True
        elif invoice.items:
            wert_fehler, wert_fehler_flag = _pruefe_abzug_wert(invoice.items, abzug_betrag)
            fehler.extend(wert_fehler)
            abzug_fehler = abzug_fehler or wert_fehler_flag
    return fehler, abzug_fehler


def _pruefe_abzug_wert(items, abzug_betrag) -> tuple[list[Issue], bool]:
    """Abzug gegen Satz-Eindeutigkeit und Hoehe der Positionssumme."""
    fehler: list[Issue] = []
    # Summen aus belegsummen, derselben Quelle wie im Router: hier wird
    # nichts selbst nachgerechnet.
    positionen_netto = belegsummen(items, None).positionen_netto
    if len({i.tax_rate for i in items}) > 1:
        fehler.append(Issue(
            "ABZUG_SATZ_UNEINDEUTIG", "error",
            "Abzug setzt voraus, dass alle Positionen denselben Steuersatz "
            "tragen; sonst ließe sich die Steuer auf der verminderten Basis "
            "nicht eindeutig berechnen.",
            "abzug_betrag",
        ))
    if abzug_betrag >= positionen_netto:
        fehler.append(Issue(
            "ABZUG_ZU_HOCH", "error",
            f"Abzug {abzug_betrag} erreicht oder übersteigt die "
            f"Positionssumme {positionen_netto}.",
            "abzug_betrag",
        ))
    return fehler, bool(fehler)


def _pruefe_gesamtsummen(kontext: Pruefkontext, abzug_fehler: bool) -> list[Issue]:
    invoice = kontext.invoice
    fehler: list[Issue] = []
    # Gesamtbeträge prüfen. Erwartungswerte aus belegsummen (BG-20): dieselbe
    # Quelle wie im Router. Liegt ein ABZUG-Fehler vor, ist unklar, auf welcher
    # Basis die gespeicherten Summen stehen; der Vergleich entfällt, statt
    # Meldungen zu einem bereits abgelehnten Abzug zu häufen.
    if invoice.items:
        if not abzug_fehler:
            summen = belegsummen(invoice.items, kontext.abzug_betrag)
            if abs(invoice.net_total - summen.steuerbasis) > Decimal("0.02"):
                fehler.append(Issue("NET_TOTAL_MISMATCH", "error", f"Nettosumme {invoice.net_total} stimmt nicht (erwartet {summen.steuerbasis}).", "net_total"))
            if abs(invoice.tax_total - summen.steuer) > Decimal("0.02"):
                fehler.append(Issue("TAX_TOTAL_MISMATCH", "error", f"Steuersumme {invoice.tax_total} stimmt nicht (erwartet {summen.steuer}).", "tax_total"))
            if abs(invoice.gross_total - summen.brutto) > Decimal("0.02"):
                fehler.append(Issue("GROSS_TOTAL_MISMATCH", "error", f"Bruttosumme {invoice.gross_total} stimmt nicht (erwartet {summen.brutto}).", "gross_total"))
        if kontext.steuerkategorie in KEIN_STEUERAUSWEIS and invoice.tax_total != Decimal("0"):
            fehler.append(Issue(
                "TAX_AMOUNT_MUST_BE_ZERO", "error",
                f"Bei dieser Steuerkategorie muss die Steuersumme exakt 0,00 € "
                f"betragen (gefunden {invoice.tax_total}).",
                "tax_total",
            ))
    return fehler
