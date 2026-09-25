"""Fachliche Belegartbeschreibung (docs/specs/vorabrechnung.md, Option B).

EINZIGE Quelle fuer interne Belegart-Werte, ihre Aliase, den BT-3-TypeCode
und die manuelle Waehlbarkeit. Der sichtbare PDF-Titel kommt aus
Belegdarstellung (docs/specs/belegsprache.md). Die fruehere TYPE_CODE_MAP in
zugferd_xml.py ist hierher umgezogen; ihre Aliase bleiben lesbar, und der
Name wird als abgeleitete Sicht weitergereicht (kein zweites Mapping).

Zwei reale Adapter lesen aus derselben Beschreibung: die XML schreibt BT-3,
das PDF den Titel ueber Belegdarstellung.titel(intern); das Formular hat
zusaetzlich eine engere Auswahl (manuelle Waehlbarkeit). 381/384/389 sind
allgemein gueltige Codes, aber keine manuelle Wahl: Gutschrift/Storno entsteht
im Stornoweg, 389 im Integrationsweg aus signierten Uebergabebelegen, 384 ist
systemreserviert.
"""
from __future__ import annotations

from dataclasses import dataclass


class UnknownInvoiceTypeError(ValueError):
    """invoice_type ist weder None noch ein bekannter Typ — fail-closed statt stillem
    Fallback auf 380 (Standardrechnung), der einen Storno/Korrektur mislabeln würde."""


class InvoiceTypeNotSelectable(ValueError):
    """Formularwert ist keine manuell waehlbare Belegart.

    Eine eigene Pruefung, kein Nebenprodukt der Typtabelle: 381 und 389 sind
    allgemein gueltige Codes, Mitgliedschaft in TYPE_CODE_MAP wuerde sie als
    manuelle Wahl durchlassen. Der Fehlercode steht im Text, damit er in der
    HTTP-400-Antwort sichtbar ist.
    """

    code = "INVOICE_TYPE_NOT_SELECTABLE"

    def __init__(self, wert):
        self.wert = wert
        super().__init__(
            f"{self.code}: Belegart {wert!r} ist nicht manuell waehlbar. "
            "Waehlbar sind nur Standardrechnung und Anzahlungsrechnung; "
            "Gutschrift, Korrektur und Gutschriftverfahren entstehen auf "
            "ihren eigenen Wegen."
        )


@dataclass(frozen=True, slots=True)
class Belegart:
    """Eine fachliche Belegart: kanonischer interner Wert, BT-3,
    manuelle Waehlbarkeit. Der sichtbare PDF-Titel liegt in Belegdarstellung
    (docs/specs/belegsprache.md), nicht hier."""

    intern: str | None        # kanonischer gespeicherter Wert (None = Standard)
    bt3: str                  # BT-3, Dokumenttypcode nach UNTDID 1001
    manuell_waehlbar: bool    # im Formular an-/abwaehlbar?
    form_wert: str | None     # Wert im Formular-POST (None bei Systembelegen)
    label: str | None         # Formularbeschriftung
    braucht_original: bool    # Folgebeleg mit Pflicht-Originalbezug (BG-3)


_STANDARD = Belegart(
    intern=None, bt3="380",
    manuell_waehlbar=True, form_wert="standard", label="Standardrechnung",
    braucht_original=False,
)
# 386 (UNTDID 1001): Zahlung fuer Waren/Dienstleistungen im Voraus. Die
# Definition erwartet anschliessend einen Abzug in der finalen Rechnung; ob
# das zur reinen Restrechnung ohne Endrechnung passt, ist eine offene
# fachliche Frage, die der Auftraggeber mit dem Empfaenger klaert (Spec,
# Kernaussage). Diese Anwendung baut bewusst keine Schlussrechnung und
# schreibt kein BT-113: fuer die unbezahlte Vorausforderung entspricht
# DuePayableAmount dem eigenen Bruttobetrag.
_ANZAHLUNG = Belegart(
    intern="prepayment", bt3="386",
    manuell_waehlbar=True, form_wert="prepayment", label="Anzahlungsrechnung",
    braucht_original=False,
)
_GUTSCHRIFT = Belegart(
    intern="credit_note", bt3="381",
    manuell_waehlbar=False, form_wert=None, label=None,
    braucht_original=True,
)
_KORREKTUR = Belegart(
    intern="correction", bt3="384",
    manuell_waehlbar=False, form_wert=None, label=None,
    braucht_original=True,
)
_SELF_BILLING = Belegart(
    intern="self_billing", bt3="389",
    manuell_waehlbar=False, form_wert=None, label=None,
    braucht_original=True,
)

_ALIASES: dict[str | None, Belegart] = {
    None: _STANDARD,
    "standard": _STANDARD,
    "invoice": _STANDARD,
    "prepayment": _ANZAHLUNG,
    "credit_note": _GUTSCHRIFT,
    "credit": _GUTSCHRIFT,
    "storno": _GUTSCHRIFT,
    "correction": _KORREKTUR,
    "self_billing": _SELF_BILLING,
    "self-billing": _SELF_BILLING,
}

# Abgeleitete Sicht auf _ALIASES, keine zweite Quelle: bisherige Leser
# (zugferd_xml, validator, tests) behalten ihre Importstelle.
TYPE_CODE_MAP: dict[str | None, str] = {
    wert: art.bt3 for wert, art in _ALIASES.items()
}


def belegart(internal_value: str | None) -> Belegart:
    """Loesst einen gespeicherten internen Wert (oder Alias) auf.

    Fail-closed (#98 E10): ein unbekannter Typ wird NICHT still auf 380
    gemappt — sonst trüge die XML einen falschen Dokumenttyp (z. B. ein
    vertippter Storno als Standardrechnung). None = kein Typ gesetzt =
    380 (legitimer Default). Rohe Codes wie "386" sind keine internen Werte.
    """
    try:
        return _ALIASES[internal_value]
    except KeyError:
        raise UnknownInvoiceTypeError(
            f"Unbekannter Rechnungstyp {internal_value!r}. "
            f"Erlaubt: {', '.join(sorted(k for k in _ALIASES if k))} (oder None)."
        ) from None


def manuelle_belegarten() -> tuple[Belegart, ...]:
    """Genau die Arten, die das Formular anbietet: Standard und Anzahlung."""
    return tuple(a for a in dict.fromkeys(_ALIASES.values()) if a.manuell_waehlbar)


def manuelle_belegart(form_value: str | None) -> str | None:
    """Formularwert → kanonischer interner Wert (None = Standard).

    Ein fehlendes Feld (None) bleibt abwaertskompatibel Standard. Alles
    andere muss eine der manuellen Arten sein: die leere Zeichenfolge wird
    nicht still zu 380, und Mitgliedschaft in TYPE_CODE_MAP genuegt nicht —
    381/389 sind allgemein gueltig, aber nie eine manuelle Wahl.
    """
    if form_value is None:
        return None
    for art in manuelle_belegarten():
        if art.form_wert == form_value:
            return art.intern
    raise InvoiceTypeNotSelectable(form_value)
