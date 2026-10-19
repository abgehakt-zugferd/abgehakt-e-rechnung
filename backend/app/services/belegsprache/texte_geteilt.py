AE_HINWEIS = (
    "Steuerschuldnerschaft des Leistungsempfängers / reverse charge, "
    "Art. 196 Council Directive 2006/112/EC"
)

# vorläufig, Prüfung durch Steuerberatung offen (#156)
SELF_BILLING_STORNO_TITEL = {
    "de": "Stornierung der Gutschrift",
    "en": "Cancellation of self-billed invoice",
}

# Anlagen der Aufstellung (§ 8b): genau zwei Quellen, die internen Werte
# stehen im DB-CHECK der Tabelle; hier nur der sichtbare Name je Sprache.
ANLAGENQUELLEN: dict[str, dict[str, str]] = {
    "de": {
        "abrechnungsbericht": "Abrechnungsbericht",
        "zahlungsbericht": "Zahlungsbericht",
    },
    "en": {
        "abrechnungsbericht": "Settlement report",
        "zahlungsbericht": "Payment report",
    },
}

UNBEKANNTE_BELEGART_MELDUNG = {
    "de": "Unbekannte Belegart: {art}",
    "en": "Unknown document type: {art}",
}

SELBSTABRECHNUNG_BEZEICHNUNG = {
    "de": "Honorargutschrift",
    "en": "Self-billed Invoice",
}

HERLEITUNGSZEILE_MUSTER = {
    "de": "Bemessungsgrundlage {basis} × {satz} %",
    "en": "Assessment base {basis} × {satz} %",
}
