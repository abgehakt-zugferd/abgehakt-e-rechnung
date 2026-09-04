"""Pauschale GmbH-Steuer-Ruecklage fuer die Uebersicht.

Die Kennzahl „Geschaetzte Steuerabgaben“ nutzt diese Saetze auf den Nettoumsatz
(ohne Ausgaben im System = Gewinn-Schaetzung). Konfigurierbar in den Einstellungen.
"""
from decimal import Decimal, ROUND_HALF_UP

from app.models.company import Company

# GmbH-Planungswerte, wenn in den Einstellungen nichts gesetzt ist.
DEFAULT_KST_PERCENT = Decimal("15.00")
DEFAULT_SOLI_AUF_KST_PERCENT = Decimal("5.50")
DEFAULT_GEWERBE_HEBESATZ = 400
GEWERBESTEUER_MESSZAHL = Decimal("0.035")

KST_PERCENT_MIN = Decimal("0")
KST_PERCENT_MAX = Decimal("50")
SOLI_PERCENT_MIN = Decimal("0")
SOLI_PERCENT_MAX = Decimal("20")
HEBESATZ_MIN = 200
HEBESATZ_MAX = 900


def steuerruecklage_anteil(company: Company | None) -> Decimal:
    """Anteil auf Nettoumsatz: KSt inkl. Soli plus Gewerbesteuer."""
    kst = _kst_satz(company)
    soli = _soli_auf_kst(company)
    hebesatz = Decimal(_gewerbe_hebesatz(company))
    return (
        kst * (Decimal("1") + soli)
        + GEWERBESTEUER_MESSZAHL * hebesatz / Decimal("100")
    )


def steuerruecklage_anteil_prozent(company: Company | None) -> Decimal:
    """Anteil als Prozentzahl fuer die Anzeige (z. B. 29,83)."""
    return (steuerruecklage_anteil(company) * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )


def kst_satz_percent(company: Company | None) -> Decimal:
    """Geltender KSt-Satz als Prozentzahl, auch wenn die Firma keinen hat.

    Die drei Spalten kamen erst mit Migration 010; eine Firmenzeile im
    Arbeitsspeicher (noch nicht eingefuegt) traegt sie als None. Wer die Werte
    ungeprueft in eine Anzeige gibt, bekommt dort `None` zu sehen oder, beim
    Betragsfilter, eine `InvalidOperation`. Deshalb liegt der Rueckfall hier
    und nicht in jeder Vorlage einzeln.
    """
    if company is None or company.kst_satz_percent is None:
        return DEFAULT_KST_PERCENT
    return Decimal(company.kst_satz_percent)


def soli_auf_kst_percent(company: Company | None) -> Decimal:
    """Geltender Soli-Satz auf die Koerperschaftsteuer als Prozentzahl."""
    if company is None or company.soli_auf_kst_percent is None:
        return DEFAULT_SOLI_AUF_KST_PERCENT
    return Decimal(company.soli_auf_kst_percent)


def gewerbe_hebesatz(company: Company | None) -> int:
    """Geltender Gewerbehebesatz der Gemeinde."""
    if company is None or company.gewerbe_hebesatz is None:
        return DEFAULT_GEWERBE_HEBESATZ
    return company.gewerbe_hebesatz


def _kst_satz(company: Company | None) -> Decimal:
    return kst_satz_percent(company) / Decimal("100")


def _soli_auf_kst(company: Company | None) -> Decimal:
    return soli_auf_kst_percent(company) / Decimal("100")


def _gewerbe_hebesatz(company: Company | None) -> int:
    return gewerbe_hebesatz(company)


def pruefe_eingaben(
    kst_percent: str,
    soli_percent: str,
    hebesatz: str,
) -> str | None:
    """Gibt eine Fehlermeldung zurueck oder None wenn die Werte gueltig sind."""
    try:
        kst = Decimal(kst_percent.replace(",", ".").strip())
        soli = Decimal(soli_percent.replace(",", ".").strip())
        hebe = int(hebesatz.strip())
    except (ArithmeticError, ValueError):
        return "Körperschaftsteuer, Solidaritätszuschlag und Gewerbehebesatz müssen Zahlen sein."

    if not (KST_PERCENT_MIN <= kst <= KST_PERCENT_MAX):
        return f"Körperschaftsteuer muss zwischen {KST_PERCENT_MIN} und {KST_PERCENT_MAX} % liegen."
    if not (SOLI_PERCENT_MIN <= soli <= SOLI_PERCENT_MAX):
        return f"Solidaritätszuschlag muss zwischen {SOLI_PERCENT_MIN} und {SOLI_PERCENT_MAX} % liegen."
    if not (HEBESATZ_MIN <= hebe <= HEBESATZ_MAX):
        return f"Gewerbehebesatz muss zwischen {HEBESATZ_MIN} und {HEBESATZ_MAX} liegen."
    return None
