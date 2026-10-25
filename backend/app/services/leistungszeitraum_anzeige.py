"""Leistungszeitraum als Anzeigetext (TT.MM.JJJJ–TT.MM.JJJJ).

Halbgeviertstrich zwischen den Daten, wie in der PDF-Darstellung des
Leistungszeitraums. Fuer den Abrechnungsauftrag: Gutschriften koennen
mehrmonatig sein; die Monatsform der anderen Nutzlastarten reicht dort nicht.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

HALBGEVIERTSTRICH = "\u2013"


def _tag(wert) -> Optional[date]:
    if not isinstance(wert, str):
        return None
    try:
        return date.fromisoformat(wert)
    except ValueError:
        return None


def _deutsch(tag: date) -> str:
    return tag.strftime("%d.%m.%Y")


def zeitraum_text(zeitraum) -> str:
    """Ein Leistungszeitraum-Objekt als TT.MM.JJJJ–TT.MM.JJJJ, sonst leer."""
    if not isinstance(zeitraum, dict):
        return ""
    von = _tag(zeitraum.get("von"))
    bis = _tag(zeitraum.get("bis"))
    if von is None or bis is None:
        return ""
    return f"{_deutsch(von)}{HALBGEVIERTSTRICH}{_deutsch(bis)}"


def spanne_aus_gutschriften(gutschriften) -> str:
    """Fruehester Beginn bis spaetestes Ende aller Gutschriften."""
    if not isinstance(gutschriften, list):
        return ""
    vonen: list[date] = []
    bisen: list[date] = []
    for gutschrift in gutschriften:
        if not isinstance(gutschrift, dict):
            continue
        zeitraum = gutschrift.get("leistungszeitraum")
        if not isinstance(zeitraum, dict):
            continue
        von = _tag(zeitraum.get("von"))
        bis = _tag(zeitraum.get("bis"))
        if von is not None:
            vonen.append(von)
        if bis is not None:
            bisen.append(bis)
    if not vonen or not bisen:
        return ""
    return f"{_deutsch(min(vonen))}{HALBGEVIERTSTRICH}{_deutsch(max(bisen))}"
