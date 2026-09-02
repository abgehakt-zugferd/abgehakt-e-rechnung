"""USt-IdNr. gegen die EU-VIES-Schnittstelle pruefen (Existenz, Gueltigkeit, Name).

Kein Scheduler, kein Abruf beim Speichern: nur nach Klick, Einwilligung im Dialog,
dann POST mit bestaetigt=1. Tests nutzen httpx.MockTransport.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import httpx

VIES_ENDPOINT = "https://ec.europa.eu/taxation_customs/vies/rest-api/check-vat-number"
TIMEOUT = httpx.Timeout(12.0, connect=5.0, read=12.0)

# Griechenland: VIES erwartet EL, Schreibweise oft GR.
_VIES_LAENDER = {"GR": "EL"}

# VIES liefert fuer manche Laender Platzhalter statt eines Firmennamens.
_VIES_NAME_PLATZHALTER = frozenset({"---", "–", "-", "...", "n/a", "na", "none"})

_NAME_SUFFIX = re.compile(
    r"\b(gmbh|ag|kg|ohg|ug|e\.?k\.?|inc|llc|co|corp|limited|ltd)\b",
    re.IGNORECASE,
)

NameAbgleich = Literal["stimmt", "weicht_ab", "unbekannt"]


@dataclass(frozen=True)
class UstIdPruefungErgebnis:
    verfuegbar: bool
    gueltig: bool | None
    registrierter_name: str | None
    registrierte_adresse: str | None
    name_abgleich: NameAbgleich
    fehlercode: str | None
    geprueft_am: datetime


def normalisiere_ust_id(roh: str | None) -> str | None:
    if not (roh or "").strip():
        return None
    s = re.sub(r"[\s.\-]", "", roh.strip().upper())
    if len(s) < 4 or not s[:2].isalpha():
        return None
    return s


def aufteilen_ust_id(ust_id: str) -> tuple[str, str] | None:
    """(VIES-Laendercode, Nummer ohne Laenderprefix)."""
    kanonisch = normalisiere_ust_id(ust_id)
    if not kanonisch:
        return None
    prefix = kanonisch[:2]
    nummer = kanonisch[2:]
    if not nummer or not re.fullmatch(r"[A-Z0-9]+", nummer):
        return None
    vies_land = _VIES_LAENDER.get(prefix, prefix)
    return vies_land, nummer


def pruefe_ust_id_format(roh: str | None) -> str | None:
    """Fehlermeldung oder None."""
    if not (roh or "").strip():
        return None
    if aufteilen_ust_id(roh) is None:
        return (
            "USt-IdNr. unlesbar: zwei Buchstaben Laendercode gefolgt von der Nummer "
            "(z. B. Laendercode DE und neun Ziffern), ohne Leerzeichen."
        )
    return None


def eingaben_fuer_pruefung(
    form_vat_id: str,
    gespeichert_vat_id: str | None,
    form_name: str,
    gespeichert_name: str,
) -> tuple[str | None, str, str | None]:
    """(vat_id, trader_name, fehlermeldung) aus Formular und gespeichertem Stand."""
    roh = (form_vat_id or "").strip() or (gespeichert_vat_id or "")
    if not roh:
        return None, gespeichert_name, "Keine USt-IdNr. zum Pruefen."
    neu = normalisiere_ust_id(roh)
    if not neu:
        return None, gespeichert_name, "USt-IdNr. unlesbar."
    fmt = pruefe_ust_id_format(neu)
    if fmt:
        return neu, gespeichert_name, fmt
    name = (form_name or "").strip() or gespeichert_name
    return neu, name, None


def vies_name_normalisiert(roh: str | None) -> str | None:
    """Registrierter Name aus VIES oder None, wenn kein vergleichbarer Name."""
    s = (roh or "").strip()
    if not s:
        return None
    if s.casefold() in _VIES_NAME_PLATZHALTER or set(s) <= {"-", "–"}:
        return None
    return s


def vies_name_vergleichbar(roh: str | None) -> str:
    return vies_name_normalisiert(roh) or ""


def _namen_normalisieren(name: str) -> str:
    s = _NAME_SUFFIX.sub("", name.casefold())
    s = re.sub(r"[^\w]+", " ", s)
    return " ".join(s.split())


def namen_gleich(erwartet: str, vies_name: str) -> bool:
    a = _namen_normalisieren(erwartet)
    b = _namen_normalisieren(vies_name)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _name_abgleich(
    trader_name_match: str | None,
    vies_name: str | None,
    erwartet: str | None,
) -> NameAbgleich:
    if trader_name_match == "VALID":
        return "stimmt"
    if trader_name_match == "INVALID":
        if not (erwartet or "").strip():
            return "unbekannt"
        return "weicht_ab"
    if vies_name and erwartet:
        return "stimmt" if namen_gleich(erwartet, vies_name) else "weicht_ab"
    return "unbekannt"


def _requester_teilen(requester_ust_id: str | None) -> tuple[str, str] | None:
    if not requester_ust_id:
        return None
    return aufteilen_ust_id(requester_ust_id)


def pruefe_ust_id_vies(
    ust_id: str,
    trader_name: str | None = None,
    requester_ust_id: str | None = None,
    endpoint: str = VIES_ENDPOINT,
    transport: httpx.BaseTransport | None = None,
) -> UstIdPruefungErgebnis:
    jetzt = datetime.now(timezone.utc)
    teile = aufteilen_ust_id(ust_id)
    if teile is None:
        return UstIdPruefungErgebnis(
            verfuegbar=False,
            gueltig=None,
            registrierter_name=None,
            registrierte_adresse=None,
            name_abgleich="unbekannt",
            fehlercode="INVALID_FORMAT",
            geprueft_am=jetzt,
        )
    land, nummer = teile
    payload: dict[str, str] = {"countryCode": land, "vatNumber": nummer}
    if trader_name and trader_name.strip():
        payload["traderName"] = trader_name.strip()
    requester = _requester_teilen(requester_ust_id)
    if requester:
        payload["requesterMemberStateCode"] = requester[0]
        payload["requesterNumber"] = requester[1]

    try:
        with httpx.Client(transport=transport, timeout=TIMEOUT) as client:
            response = client.post(endpoint, json=payload)
    except httpx.HTTPError as fehler:
        return UstIdPruefungErgebnis(
            verfuegbar=False,
            gueltig=None,
            registrierter_name=None,
            registrierte_adresse=None,
            name_abgleich="unbekannt",
            fehlercode=f"HTTP_{type(fehler).__name__}",
            geprueft_am=jetzt,
        )

    if response.status_code != 200:
        return UstIdPruefungErgebnis(
            verfuegbar=False,
            gueltig=None,
            registrierter_name=None,
            registrierte_adresse=None,
            name_abgleich="unbekannt",
            fehlercode=f"HTTP_{response.status_code}",
            geprueft_am=jetzt,
        )

    try:
        data = response.json()
    except ValueError:
        return UstIdPruefungErgebnis(
            verfuegbar=False,
            gueltig=None,
            registrierter_name=None,
            registrierte_adresse=None,
            name_abgleich="unbekannt",
            fehlercode="INVALID_JSON",
            geprueft_am=jetzt,
        )

    if data.get("userError"):
        return UstIdPruefungErgebnis(
            verfuegbar=False,
            gueltig=None,
            registrierter_name=None,
            registrierte_adresse=None,
            name_abgleich="unbekannt",
            fehlercode=str(data.get("userError")),
            geprueft_am=jetzt,
        )

    wrappers = data.get("errorWrappers") or []
    if wrappers:
        code = wrappers[0].get("error") if isinstance(wrappers[0], dict) else str(wrappers[0])
        return UstIdPruefungErgebnis(
            verfuegbar=False,
            gueltig=None,
            registrierter_name=None,
            registrierte_adresse=None,
            name_abgleich="unbekannt",
            fehlercode=code or "VIES_ERROR",
            geprueft_am=jetzt,
        )

    gueltig = bool(data.get("valid"))
    vies_name = vies_name_normalisiert((data.get("name") or "").strip() or None)
    vies_adresse = (data.get("address") or "").strip() or None
    trader_match = data.get("traderNameMatch")

    return UstIdPruefungErgebnis(
        verfuegbar=True,
        gueltig=gueltig,
        registrierter_name=vies_name,
        registrierte_adresse=vies_adresse,
        name_abgleich=_name_abgleich(trader_match, vies_name, trader_name),
        fehlercode=None,
        geprueft_am=jetzt,
    )


def zuruecksetzen(entity) -> None:
    entity.vat_id_checked_at = None
    entity.vat_id_check_valid = None
    entity.vat_id_vies_name = None
    entity.vat_id_name_match = None


def speichern(entity, ergebnis: UstIdPruefungErgebnis) -> None:
    entity.vat_id_checked_at = ergebnis.geprueft_am
    if ergebnis.verfuegbar:
        entity.vat_id_check_valid = ergebnis.gueltig
        entity.vat_id_vies_name = ergebnis.registrierter_name
        entity.vat_id_name_match = ergebnis.name_abgleich
    else:
        entity.vat_id_check_valid = None
        entity.vat_id_vies_name = None
        entity.vat_id_name_match = None


def status_text(entity) -> str | None:
    if not getattr(entity, "vat_id", None):
        return None
    if not entity.vat_id_checked_at:
        return "Noch nicht bei VIES geprueft."
    if entity.vat_id_check_valid is None:
        return "VIES war beim letzten Versuch nicht erreichbar; Gueltigkeit unbekannt."
    if not entity.vat_id_check_valid:
        return "VIES meldet: USt-IdNr. ungueltig oder nicht registriert."
    teile = ["VIES: gueltig"]
    if entity.vat_id_vies_name:
        teile.append(f"Registrierter Name: {entity.vat_id_vies_name}")
    match = entity.vat_id_name_match
    if match == "stimmt":
        teile.append("Name stimmt mit dem hinterlegten Namen ueberein.")
    elif match == "weicht_ab":
        teile.append("Name weicht vom hinterlegten Namen ab.")
    else:
        teile.append("Name konnte nicht abgeglichen werden (VIES liefert fuer dieses Land oft keinen Namen).")
    return " ".join(teile)
