"""Zahlungstext in der Belegsprache: eine Regel fuer Speichern und Finalisieren (#248, #260).

Leeres Feld: Zahlungshinweis des Kunden, sonst Firmenvorgabe der Belegsprache.
Steht genau die Firmenvorgabe der anderen Sprache im Feld, wird sie ersetzt,
und zwar mit derselben Rangfolge (Kundenhinweis vor Firmenvorgabe). Freitext
bleibt unveraendert. Der Dienst kennt kein HTTP: fehlt die englische Vorgabe
und gibt es keinen Kundenhinweis, meldet er `ZahlungsvorgabeFehlt`.
"""
from __future__ import annotations

FEHLT_EN = (
    "Englische Standard-Zahlungsbedingungen fehlen in den Einstellungen. "
    "Bitte zuerst unter Einstellungen hinterlegen."
)


class ZahlungsvorgabeFehlt(Exception):
    """Die Firmenvorgabe der Belegsprache fehlt und kein Kundenhinweis springt ein."""


def _vorgabe(company, sprache: str) -> str:
    feld = "payment_terms_default_en" if sprache == "en" else "payment_terms_default"
    return (getattr(company, feld, None) or "").strip()


def ist_vorgabe_der_anderen_sprache(eingabe: str | None, company, sprache: str) -> bool:
    """True, wenn das Feld genau die Firmenvorgabe der anderen Sprache traegt."""
    text = (eingabe or "").strip()
    andere = "de" if sprache == "en" else "en"
    vorgabe = _vorgabe(company, andere)
    return bool(text and vorgabe and text == vorgabe)


def _kundenhinweis_oder_vorgabe(company, sprache: str, kunden_hinweis: str | None) -> str:
    hinweis = (kunden_hinweis or "").strip()
    if hinweis:
        return hinweis
    vorgabe = _vorgabe(company, sprache)
    if not vorgabe and sprache == "en":
        raise ZahlungsvorgabeFehlt(FEHLT_EN)
    return vorgabe


def zahlungstext_in_belegsprache(eingabe: str | None, company, sprache: str,
                                 kunden_hinweis: str | None = None) -> str:
    """Zahlungstext des Belegs nach der gemeinsamen Regel (siehe Modulkopf)."""
    text = (eingabe or "").strip()
    if text and not ist_vorgabe_der_anderen_sprache(text, company, sprache):
        return text
    return _kundenhinweis_oder_vorgabe(company, sprache, kunden_hinweis)
