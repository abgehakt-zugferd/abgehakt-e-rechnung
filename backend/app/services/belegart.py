"""Fachliche Belegartbeschreibung (docs/specs/vorabrechnung.md, Option B).

EINZIGE Quelle fuer interne Belegart-Werte, ihre Aliase, den BT-3-TypeCode
und die manuelle Waehlbarkeit. Der sichtbare PDF-Titel kommt aus
Belegdarstellung (docs/specs/belegsprache.md). Die fruehere TYPE_CODE_MAP in
zugferd_xml.py ist hierher umgezogen; ihre Aliase bleiben lesbar, und der
Name wird als abgeleitete Sicht weitergereicht (kein zweites Mapping).

Zwei reale Adapter lesen aus derselben Beschreibung: die XML schreibt BT-3,
das PDF den Titel ueber Belegdarstellung.titel(intern); das Formular hat
zusaetzlich eine engere Auswahl (manuelle Waehlbarkeit). 381/384 und das
389-Storno sind Systembelege. 389 entsteht entweder manuell
oder im Integrationsweg aus signierten Uebergabebelegen; dort bleiben die
gebundenen Felder durch die Herkunft gesperrt.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_


class UnknownInvoiceTypeError(ValueError):
    """invoice_type ist weder None noch ein bekannter Typ — fail-closed statt stillem
    Fallback auf 380 (Standardrechnung), der einen Storno/Korrektur mislabeln würde."""


class InvoiceTypeNotSelectable(ValueError):
    """Formularwert ist keine manuell waehlbare Belegart.

    Eine eigene Pruefung, kein Nebenprodukt der Typtabelle: 381 und 384 sind
    allgemein gueltige Codes, Mitgliedschaft in TYPE_CODE_MAP wuerde sie als
    manuelle Wahl durchlassen. Der Fehlercode steht im Text, damit er in der
    HTTP-400-Antwort sichtbar ist.
    """

    code = "INVOICE_TYPE_NOT_SELECTABLE"

    def __init__(self, wert):
        self.wert = wert
        super().__init__(
            f"{self.code}: Belegart {wert!r} ist nicht manuell waehlbar. "
            "Waehlbar sind Standardrechnung, Anzahlungsrechnung und Honorargutschrift; "
            "Storno und Korrektur entstehen auf "
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
    manuell_waehlbar=True, form_wert="honorargutschrift",
    label="Honorargutschrift (Gutschriftverfahren)",
    braucht_original=False,
)

# vorläufig, Prüfung durch Steuerberatung offen (#156)
SELF_BILLING_STORNO_BT3 = "261"
_SELF_BILLING_STORNO = Belegart(
    intern="self_billing_storno", bt3=SELF_BILLING_STORNO_BT3,
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
    "self_billing_storno": _SELF_BILLING_STORNO,
}

# Abgeleitete Sicht auf _ALIASES, keine zweite Quelle: bisherige Leser
# (zugferd_xml, validator, tests) behalten ihre Importstelle.
TYPE_CODE_MAP: dict[str | None, str] = {
    wert: art.bt3 for wert, art in _ALIASES.items()
}

# Interne Formen, die ein Original aufheben (381 bzw. 389-Storno). Eine Quelle
# fuer Python-Praedikat und SQL-Rohwertmenge (Issue #172).
_STORNO_INTERN = frozenset({"credit_note", "self_billing_storno"})


def rohwerte(*interne: str | None) -> frozenset[str | None]:
    """Alle Rohwerte aus _ALIASES, die auf eine der genannten internen Formen zeigen.

    Fuer SQL-Filter: ueber belegart_filter(spalte, ...), nicht handgebaut.
    Keine zweite handgepflegte Liste.
    """
    ziel = frozenset(interne)
    return frozenset(roh for roh, art in _ALIASES.items() if art.intern in ziel)


def belegart_filter(spalte, *interne: str | None):
    """SQL-Bedingung: Spalte trifft eine der internen Belegarten inkl. Aliase.

    Baut aus rohwerte das passende or_(spalte.is_(None), spalte.in_(...)):
    is_(None) nur, wenn None zu den Rohwerten gehoert (Standardrechnung und
    ihre Aliase "standard"/"invoice"). Einzige erlaubte SQL-Naht fuer
    invoice_type-Filter ausserhalb dieses Moduls (Issue #172).
    """
    roh = rohwerte(*interne)
    teile: list = []
    if None in roh:
        teile.append(spalte.is_(None))
    nicht_none = frozenset(r for r in roh if r is not None)
    if nicht_none:
        teile.append(spalte.in_(nicht_none))
    if not teile:
        return spalte.in_([])  # nie wahr, leere Zielmenge
    if len(teile) == 1:
        return teile[0]
    return or_(*teile)


def invoice_type_ungesetzt(spalte):
    """SQL: invoice_type IS NULL, ohne Formular-Alias.

    Rechnungsauftrag (#206/#227) und der CHECK verlangen NULL, nicht
    'standard'. belegart_filter(..., None) waere weiter (Aliase).
    """
    return spalte.is_(None)


# Gutschriften im Geldfluss samt Alias-Schreibweisen. Abgeleitet aus _ALIASES
# (Issue #172), bewusst ohne 389-Storno und ohne Korrektur — siehe zahlung_an_kunde.
# Einzige verbleibende Leserin: pruefregeln/empfehlungen.py (Kunden-IBAN-Warnung).
GUTSCHRIFT_TYPEN = frozenset(
    k for k in rohwerte("credit_note", "self_billing") if k is not None
)


def ist_storno(invoice_type: str | None) -> bool:
    """True, wenn die Belegart ein Original aufhebt (Gutschrift oder 389-Storno)."""
    return belegart(invoice_type).intern in _STORNO_INTERN


def zahlung_an_kunde(invoice_type: str | None) -> bool:
    """Zahlungsfluss dieser Belegart geht an den KUNDEN (nicht an die Firma).

    PDF-Bankblock und XML-PaymentMeans rufen das hier ab. Entscheidend ist die
    aufgeloeste Belegart, damit gespeicherte Aliase ("self-billing", "credit",
    "storno") mitgemeint sind — belegrollen.besetzung loest genauso auf, die
    rohe Menge in GUTSCHRIFT_TYPEN tat es nicht. Bewusst False fuer das
    389-Storno (261): der Geldfluss kehrt sich um, der Kunde zahlt der Firma.
    Ein unbekannter Wert zahlt niemals an den Kunden (False statt Wurf)."""
    try:
        return belegart(invoice_type).intern in {"credit_note", "self_billing"}
    except UnknownInvoiceTypeError:
        return False


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


def belegart_aus_bt3(type_code: str | None) -> Belegart:
    """Loesst einen BT-3-TypeCode auf die kanonische Belegart.

    Abgeleitet aus denselben Belegart-Werten wie TYPE_CODE_MAP, keine zweite
    Tabelle. Fehlender oder unbekannter Code: fail-closed statt still 380.
    """
    code = (type_code or "").strip()
    if not code:
        raise UnknownInvoiceTypeError("TypeCode (BT-3) fehlt in der XML.")
    for art in dict.fromkeys(_ALIASES.values()):
        if art.bt3 == code:
            return art
    erlaubt = ", ".join(sorted({a.bt3 for a in _ALIASES.values()}))
    raise UnknownInvoiceTypeError(
        f"Unbekannter TypeCode {code!r} (BT-3). Erlaubt: {erlaubt}."
    )


def manuelle_belegarten() -> tuple[Belegart, ...]:
    """Genau die Arten, die das Formular anbietet: Standard, Anzahlung und Honorargutschrift."""
    return tuple(a for a in dict.fromkeys(_ALIASES.values()) if a.manuell_waehlbar)


def manuelle_belegart(form_value: str | None) -> str | None:
    """Formularwert → kanonischer interner Wert (None = Standard).

    Ein fehlendes Feld (None) bleibt abwaertskompatibel Standard. Alles
    andere muss eine der manuellen Arten sein: die leere Zeichenfolge wird
    nicht still zu 380, und Mitgliedschaft in TYPE_CODE_MAP genuegt nicht —
    381/384 sind allgemein gueltig, aber nie eine manuelle Wahl.
    """
    if form_value is None:
        return None
    for art in manuelle_belegarten():
        if art.form_wert == form_value:
            return art.intern
    raise InvoiceTypeNotSelectable(form_value)


def ist_honorargutschrift(invoice_type: str | None) -> bool:
    """Honorargutschrift einschließlich gespeicherter Aliase, ohne Storno."""
    return belegart(invoice_type) == _SELF_BILLING
