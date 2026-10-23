"""Neutrale Spaltenwerte der Belegliste aus dem Belegurteil (#207).

Das Template verzweigt nicht nach Nutzlastart: hier entsteht je Beleg
Gegenstand (Kunde oder Projekt), Zeitraum und Summe, oder leer wenn die
Nutzlast nicht lesbar ist.
"""

from decimal import Decimal, InvalidOperation
from typing import Optional

from app.services.uebergabe_befund import Belegurteil


def _geld(wert: Optional[Decimal]) -> str:
    return f"{wert:.2f}".replace(".", ",") if wert is not None else ""


def _betrag(wert) -> Optional[Decimal]:
    try:
        return Decimal(str(wert))
    except (InvalidOperation, ValueError, ArithmeticError, TypeError):
        return None


def _projektname(nutzlast: dict) -> str:
    projekt = nutzlast.get("projekt")
    if isinstance(projekt, dict):
        name = projekt.get("name")
        return name if isinstance(name, str) else ""
    return ""


def _kundenname(nutzlast: dict) -> str:
    kunde = nutzlast.get("kunde")
    if isinstance(kunde, dict):
        name = kunde.get("anzeigename")
        return name if isinstance(name, str) else ""
    return ""


def _monat(nutzlast: dict) -> str:
    zeitraum = nutzlast.get("leistungszeitraum")
    if not isinstance(zeitraum, dict):
        return ""
    von = zeitraum.get("von")
    if isinstance(von, str) and len(von) >= 7:
        return von[:7]
    return ""


def _summe_gutschriften(nutzlast: dict) -> Optional[Decimal]:
    gutschriften = nutzlast.get("gutschriften")
    if not isinstance(gutschriften, list):
        return None
    summe = Decimal("0")
    for gutschrift in gutschriften:
        if not isinstance(gutschrift, dict):
            continue
        summe_feld = gutschrift.get("summe")
        betrag = _betrag(
            summe_feld.get("netto") if isinstance(summe_feld, dict) else None
        )
        if betrag is not None:
            summe += betrag
    return summe


def _summe_mit_waehrung(betrag: Optional[Decimal], waehrung) -> str:
    text = _geld(betrag)
    if not text:
        return ""
    if isinstance(waehrung, str) and waehrung:
        return f"{text} {waehrung}"
    return text


def _aus_abrechnungsauftrag(nutzlast: dict) -> tuple[str, str, str]:
    quartal = nutzlast.get("abrechnungsquartal")
    return (
        _projektname(nutzlast),
        quartal if isinstance(quartal, str) else "",
        _geld(_summe_gutschriften(nutzlast)),
    )


def _aus_rechnungsauftrag(nutzlast: dict) -> tuple[str, str, str]:
    summe = nutzlast.get("summe")
    betrag = _betrag(summe.get("netto") if isinstance(summe, dict) else None)
    return (
        _kundenname(nutzlast),
        _monat(nutzlast),
        _summe_mit_waehrung(betrag, nutzlast.get("waehrung")),
    )


def _aus_aufstellungsauftrag(nutzlast: dict) -> tuple[str, str, str]:
    betraege = nutzlast.get("betraege")
    betrag = _betrag(
        betraege.get("netto") if isinstance(betraege, dict) else None
    )
    return (
        _kundenname(nutzlast),
        _monat(nutzlast),
        _summe_mit_waehrung(betrag, nutzlast.get("waehrung")),
    )


_ZUORDNUNG = {
    "abrechnungsauftrag": _aus_abrechnungsauftrag,
    "rechnungsauftrag": _aus_rechnungsauftrag,
    "aufstellungsauftrag": _aus_aufstellungsauftrag,
}


def listenfelder(urteil: Belegurteil) -> dict:
    """Gegenstand, Zeitraum und Summe fuer eine Tabellenzeile."""
    leer = {"gegenstand": "", "zeitraum": "", "summe": ""}
    nutzlast = urteil.nutzlast
    art = urteil.nutzlast_art
    if not isinstance(nutzlast, dict) or art not in _ZUORDNUNG:
        return leer
    gegenstand, zeitraum, summe = _ZUORDNUNG[art](nutzlast)
    return {
        "gegenstand": gegenstand or "",
        "zeitraum": zeitraum or "",
        "summe": summe or "",
    }


def zeile_aus_urteil(dateiname: str, urteil: Belegurteil) -> dict:
    """Eine Zeile der Belegliste: Datei, Urteil und neutrale Anzeigefelder."""
    felder = listenfelder(urteil)
    return {
        "dateiname": dateiname,
        "urteil": urteil,
        "erzeugt_am": (
            urteil.erzeugt_am.strftime("%d.%m.%Y %H:%M")
            if urteil.erzeugt_am else ""
        ),
        "gegenstand": felder["gegenstand"],
        "zeitraum": felder["zeitraum"],
        "summe": felder["summe"],
    }
