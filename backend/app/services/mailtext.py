"""Betreff und Rumpf der Rechnungsmail je Belegsprache.

Reine Textlogik ohne SMTP und ohne HTTP. Die Sprache kommt ausschliesslich
aus `invoice.document_language` ueber `belegsprache.resolve_belegsprache`.
Platzhalter werden mit einem engen Ausdruck ersetzt, nicht mit der
eingebauten Formatmethode von str und nicht mit einer Schablonensprache.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.services.belegsprache import Belegsprache, darstellung, resolve_belegsprache

PLATZHALTER: tuple[str, ...] = (
    "rechnungsnummer",
    "kunde",
    "betrag",
    "faellig_am",
    "firma",
)

_PLATZHALTER_RE = re.compile(r"\{([a-z_]+)\}")

_STANDARD_BETREFF = {
    "de": "Rechnung {rechnungsnummer}",
    "en": "Invoice {rechnungsnummer}",
}

_STANDARD_RUMPF_DE = (
    "Sehr geehrte Damen und Herren,\n"
    "\n"
    "anbei erhalten Sie Ihre Rechnung {rechnungsnummer}.\n"
    "\n"
    "Das Dokument enthält die strukturierten ZUGFeRD-Rechnungsdaten "
    "(Factur-X EN16931) gemäß § 14 UStG.\n"
    "\n"
    "Bei Fragen stehen wir Ihnen gerne zur Verfügung.\n"
    "\n"
    "Mit freundlichen Grüßen\n"
    "{firma}"
)

_STANDARD_RUMPF_EN = (
    "Dear Sir or Madam,\n"
    "\n"
    "please find attached your invoice {rechnungsnummer}.\n"
    "\n"
    "The document contains the structured ZUGFeRD invoice data (Factur-X EN16931)\n"
    "pursuant to section 14 of the German VAT Act (UStG).\n"
    "\n"
    "Please do not hesitate to contact us if you have any questions.\n"
    "\n"
    "Kind regards\n"
    "{firma}"
)

_STANDARD_RUMPF = {"de": _STANDARD_RUMPF_DE, "en": _STANDARD_RUMPF_EN}

_FUSS_LABEL = {"de": "Verantwortlich:", "en": "Responsible:"}


class UnbekannterPlatzhalterError(ValueError):
    """Schablone enthaelt einen Platzhalter, der nicht in PLATZHALTER steht."""

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Unbekannter Platzhalter: {{{name}}}")


@dataclass(frozen=True, slots=True)
class Schablone:
    betreff: str
    rumpf: str


@dataclass(frozen=True, slots=True)
class Mailinhalt:
    betreff: str
    rumpf: str


def standardschablone(sprache: Belegsprache) -> Schablone:
    return Schablone(betreff=_STANDARD_BETREFF[sprache], rumpf=_STANDARD_RUMPF[sprache])


def pruefe_schablone(text: str) -> None:
    for treffer in _PLATZHALTER_RE.finditer(text or ""):
        name = treffer.group(1)
        if name not in PLATZHALTER:
            raise UnbekannterPlatzhalterError(name)


def _anschrift(company) -> str:
    """Name, Strasse, PLZ Ort — leer, wenn die Firma unvollstaendig ist."""
    if not company:
        return ""
    teile = [(company.name or "").strip(), (company.address_line1 or "").strip()]
    ort = " ".join(
        t for t in ((company.zip_code or "").strip(), (company.city or "").strip()) if t
    )
    teile.append(ort)
    return ", ".join(t for t in teile if t)


def _schablone_aus_config(config, sprache: Belegsprache) -> Schablone:
    standard = standardschablone(sprache)
    if config is None:
        return standard
    if sprache == "de":
        betreff = getattr(config, "mail_betreff_de", None)
        rumpf = getattr(config, "mail_text_de", None)
    else:
        betreff = getattr(config, "mail_betreff_en", None)
        rumpf = getattr(config, "mail_text_en", None)
    betreff = (betreff or "").strip() or standard.betreff
    rumpf = (rumpf or "").strip() or standard.rumpf
    return Schablone(betreff=betreff, rumpf=rumpf)


def _werte(invoice, company, sprache: Belegsprache) -> dict[str, str]:
    form = darstellung(sprache)
    kunde = ""
    customer = getattr(invoice, "customer", None)
    if customer is not None:
        kunde = (getattr(customer, "name", None) or "").strip()
    firma = (company.name or "").strip() if company else ""
    faellig = ""
    if getattr(invoice, "due_date", None) is not None:
        faellig = form.format_datum(invoice.due_date)
    betrag = form.format_betrag(invoice.gross_total, invoice.currency or "EUR")
    return {
        "rechnungsnummer": invoice.invoice_number or "",
        "kunde": kunde,
        "betrag": betrag,
        "faellig_am": faellig,
        "firma": firma,
    }


def _ersetze(text: str, werte: dict[str, str]) -> str:
    def ersatz(treffer: re.Match[str]) -> str:
        name = treffer.group(1)
        if name in werte:
            return werte[name]
        return treffer.group(0)

    return _PLATZHALTER_RE.sub(ersatz, text)


def _ohne_leerzeilen_am_ende(text: str) -> str:
    zeilen = text.split("\n")
    while zeilen and zeilen[-1].strip() == "":
        zeilen.pop()
    return "\n".join(zeilen)


def _fuss(company, sprache: Belegsprache) -> str:
    anschrift = _anschrift(company)
    if not anschrift:
        return ""
    return f"\n\n---\n{_FUSS_LABEL[sprache]} {anschrift}"


def rechnungsmail(invoice, company, config) -> Mailinhalt:
    sprache = resolve_belegsprache(getattr(invoice, "document_language", None))
    schablone = _schablone_aus_config(config, sprache)
    werte = _werte(invoice, company, sprache)
    betreff = _ersetze(schablone.betreff, werte)
    rumpf = _ohne_leerzeilen_am_ende(_ersetze(schablone.rumpf, werte))
    rumpf = rumpf + _fuss(company, sprache) + "\n"
    return Mailinhalt(betreff=betreff, rumpf=rumpf)
