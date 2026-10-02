"""Pflichtangaben auf Geschäftsbriefen, also auch auf jeder Rechnung.

Einzige Quelle für vier Abnehmer: PDF-Fuß, ZUGFeRD-XML (BT-30, BT-33), die Sperre
beim Stellen (validator) und das Einstellungsformular. Welche Rechtsform welche
Angabe verlangt, steht nur hier.
"""
from dataclasses import dataclass

from app.models.company import Company
from app.services.belegsprache import Belegsprache


@dataclass(frozen=True)
class _Regel:
    bezeichnung: str
    register: bool
    grundlage: str | None = None
    # Schlüssel in _BESCHRIFTUNG; None: die Vertretung ist keine Pflichtangabe.
    vertretung: str | None = None
    # "pflicht" (AG), "wenn_gebildet" (GmbH, UG: § 35a Abs. 1 Satz 1 GmbHG), None.
    aufsichtsrat: str | None = None


_REGELN: dict[str, _Regel] = {
    "einzelunternehmen": _Regel("Einzelunternehmen oder Freiberuf, nicht im Handelsregister",
                                register=False),
    "ek": _Regel("Eingetragene Kauffrau / eingetragener Kaufmann (e.K.)", register=True,
                 grundlage="§ 37a HGB"),
    "ohg": _Regel("Offene Handelsgesellschaft (OHG)", register=True, grundlage="§ 125a HGB"),
    "kg": _Regel("Kommanditgesellschaft (KG)", register=True, grundlage="§ 125a HGB"),
    "partg": _Regel("Partnerschaftsgesellschaft (PartG)", register=True,
                    grundlage="§ 7 Abs. 5 PartGG"),
    "gmbh": _Regel("Gesellschaft mit beschränkter Haftung (GmbH)", register=True,
                   grundlage="§ 35a GmbHG",
                   vertretung="geschaeftsfuehrung", aufsichtsrat="wenn_gebildet"),
    "ug": _Regel("Unternehmergesellschaft (haftungsbeschränkt)", register=True,
                 grundlage="§ 35a GmbHG",
                 vertretung="geschaeftsfuehrung", aufsichtsrat="wenn_gebildet"),
    "ag": _Regel("Aktiengesellschaft (AG)", register=True,
                 grundlage="§ 80 AktG",
                 vertretung="vorstand", aufsichtsrat="pflicht"),
    "sonstige": _Regel("Andere Rechtsform (z. B. eG, e.V.), Angaben selbst prüfen",
                       register=False),
}

# Wie ein fehlendes Feld in Meldungen heißt.
_FELDBEZEICHNUNG: dict[str, str] = {
    "rechtsform": "Rechtsform",
    "registergericht": "Registergericht",
    "registernummer": "Registernummer",
    "vertretung": "Vertretung (Geschäftsführung, Vorstand)",
    "aufsichtsrat_vorsitz": "Vorsitz des Aufsichtsrats",
}

# Auswahl im Formular, in dieser Reihenfolge.
RECHTSFORMEN: dict[str, str] = {k: r.bezeichnung for k, r in _REGELN.items()}


_TRENNER = "  ·  "

# Nur die Bezeichner folgen der Belegsprache; die Werte (Amtsgericht, HRB) bleiben,
# wie sie im Register stehen.
_BESCHRIFTUNG: dict[str, dict[str, str]] = {
    "de": {
        "sitz": "Sitz",
        "registergericht": "Registergericht",
        "geschaeftsfuehrung": "Geschäftsführung",
        "vorstand": "Vorstand",
        "aufsichtsrat": "Vorsitz des Aufsichtsrats",
    },
    "en": {
        "sitz": "Registered office",
        "registergericht": "Register court",
        "geschaeftsfuehrung": "Managing directors",
        "vorstand": "Executive board",
        "aufsichtsrat": "Chair of the supervisory board",
    },
}


@dataclass(frozen=True)
class Pflichtangaben:
    zeilen: tuple[str, ...]
    # Feldnamen an `Company`, die für diese Rechtsform fehlen. Leer: vollständig.
    fehlend: tuple[str, ...]
    # BT-30 der E-Rechnung; nur bei registerpflichtigen Rechtsformen.
    registernummer: str | None = None
    # Norm, die die Angaben verlangt, für Meldungen.
    grundlage: str | None = None

    def luecke(self) -> str | None:
        """Fehlende Angaben in Worten, mit Norm; None, wenn nichts fehlt."""
        if not self.fehlend:
            return None
        text = ", ".join(_FELDBEZEICHNUNG[f] for f in self.fehlend)
        return f"{text} ({self.grundlage})" if self.grundlage else text


def _wert(text: str | None) -> str:
    return (text or "").strip()


def pflichtangaben(company: Company, sprache: Belegsprache = "de") -> Pflichtangaben:
    regel = _REGELN.get(company.rechtsform or "")
    if regel is None:
        return Pflichtangaben(zeilen=(), fehlend=("rechtsform",))
    verlangt: list[str] = []
    if regel.register:
        verlangt += ["registergericht", "registernummer"]
    if regel.vertretung:
        verlangt.append("vertretung")
    if regel.aufsichtsrat == "pflicht":
        verlangt.append("aufsichtsrat_vorsitz")
    fehlend = tuple(feld for feld in verlangt if not _wert(getattr(company, feld)))

    b = _BESCHRIFTUNG[sprache]
    zeilen: list[str] = []
    if regel.register:
        teile = [f"{b['sitz']}: {_wert(company.sitz) or _wert(company.city)}"]
        register = ", ".join(
            w for w in (_wert(company.registergericht), _wert(company.registernummer)) if w
        )
        if register:
            teile.append(f"{b['registergericht']}: {register}")
        zeilen.append(_TRENNER.join(teile))
    organe = []
    if regel.vertretung and _wert(company.vertretung):
        organe.append(f"{b[regel.vertretung]}: {_wert(company.vertretung)}")
    if regel.aufsichtsrat and _wert(company.aufsichtsrat_vorsitz):
        organe.append(f"{b['aufsichtsrat']}: {_wert(company.aufsichtsrat_vorsitz)}")
    if organe:
        zeilen.append(_TRENNER.join(organe))
    return Pflichtangaben(
        zeilen=tuple(zeilen), fehlend=fehlend,
        registernummer=(_wert(company.registernummer) or None) if regel.register else None,
        grundlage=regel.grundlage,
    )
