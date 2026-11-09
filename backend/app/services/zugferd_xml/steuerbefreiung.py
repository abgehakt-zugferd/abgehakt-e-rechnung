"""Steuerbefreiungstexte und Profil-Kennungen fuer die CII-Erzeugung."""
from app.models.invoice import Invoice
from app.services.belegart import im_gutschriftverfahren
from app.services.belegsprache import darstellung, resolve_belegsprache

PROFILE_IDS = {
    # ZUGFeRD 2.5 / Factur-X 1.09 (gültig ab 30.06.2026): EN16931-ID vereinfacht
    "EN16931": "urn:cen.eu:en16931:2017",
    "BASIC": "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic",
    "XRECHNUNG": "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_2.3",
}

# Rechtlich zulässige (EN16931-konforme) Profile, die dieses System rendert.
# MINIMUM und BASIC-WL sind KEINE gültige E-Rechnung (§ 14 UStG verlangt mind.
# EN16931) — sie werden NICHT still auf EN16931 gemappt, sondern hart abgelehnt.
COMPLIANT_PROFILES = frozenset(PROFILE_IDS)


class NonCompliantProfileError(ValueError):
    """Nicht-EN16931-konformes ZUGFeRD-Profil (z. B. MINIMUM, BASIC-WL) — als
    E-Rechnung unzulässig. Fail-closed statt stillem Fallback auf EN16931."""

# Ohne diesen Text ist eine Rechnung der Kategorie "E" schema-ungültig: EN16931
# verlangt über BR-E-10 zu jeder Steuergruppe "Exempt from VAT" einen Grund
# (BT-120 Text oder BT-121 Code). Fachlich verlangt § 14 Abs. 4 Nr. 8 UStG
# denselben Hinweis auf dem Beleg. Kein Eintrag hier ⇒ keine Rechnung.
EXEMPTION_REASONS = {
    "AE": "Steuerschuldnerschaft des Leistungsempfängers / reverse charge, Art. 196 Council Directive 2006/112/EC",
    "E": "Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG.",
    "K": "Steuerfreie innergemeinschaftliche Lieferung gemäß § 4 Nr. 1b UStG i.V.m. § 6a UStG.",
    "O": "Nicht im Steuergebiet des Ausstellers steuerbar gemäß § 3a Abs. 2 UStG.",
}

def exemption_reason(invoice: Invoice) -> str | None:
    """BT-120 in der Belegsprache; dieselbe Quelle wie der PDF-Hinweis.

    Unbekannte Sprache wirft UnknownDocumentLanguageError (kein stiller Rueckfall).
    Das Gutschriftverfahren (389) hat fuer Kategorie E einen eigenen Wortlaut (#148).
    """
    cat = getattr(invoice, "tax_category", "S")
    if cat not in EXEMPTION_REASONS:
        return None
    sprache = resolve_belegsprache(getattr(invoice, "document_language", None) or "de")
    return darstellung(sprache).steuerhinweis(cat, gutschriftverfahren=im_gutschriftverfahren(invoice))
