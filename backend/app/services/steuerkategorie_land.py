"""Plausibilitätsprüfung: passt die gewählte Steuerkategorie zum Kundenland? (#145)

Das ist eine Plausibilitätswarnung und keine Steuerberatung: die Regeln nennen
den Normalfall, im Einzelfall können Abweichungen zulässig sein. Deshalb wird
nie ein harter Fehler ausgelöst, sondern nur ein Text zurückgegeben, den der
Validator als Warnung anzeigt.

Die Funktion liefert bewusst KEIN Issue-Objekt zurück: Issue ist in
validator.py definiert, und validator.py importiert dieses Modul. Ein
Rückimport wäre ein Zirkelbezug.

Eine Ausnahme ist hart (#275): AE an einen Kunden mit Land DE und einer
USt-IdNr. eines anderen Landes. Die Empfaengeranschrift ist Pflichtangabe und
der Widerspruch laesst sich nach dem Stellen nur per Storno heilen.
"""
from app.services.ust_id_pruefung import normalisiere_ust_id

EU_MITGLIEDSTAATEN = frozenset({
    "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
    "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL",
    "PT", "RO", "SE", "SI", "SK",
})

_WARNUNG_INLAND = (
    "Der Kunde sitzt in Deutschland. Reverse Charge (AE), "
    "innergemeinschaftliche Lieferung (K) und nicht im Inland steuerbar (O) "
    "passen in der Regel nicht zu einem Inlandskunden. "
    "Bitte die Steuerkategorie prüfen."
)
_WARNUNG_EU = (
    "Der Kunde sitzt in einem anderen EU-Mitgliedstaat. "
    "Für sonstige Leistungen an Unternehmer dort gilt in der Regel "
    "Reverse Charge (Kategorie AE), nicht O. "
    "Bitte die Steuerkategorie prüfen."
)
_WARNUNG_DRITTLAND = (
    "Der Kunde sitzt außerhalb der EU. Reverse Charge (AE) und "
    "innergemeinschaftliche Lieferung (K) gelten nur innerhalb der EU; "
    "für sonstige Leistungen an Unternehmer im Drittland ist in der Regel "
    "Kategorie O richtig. Bitte die Steuerkategorie prüfen."
)


def kategorie_passt_zum_land(kategorie: str | None, kundenland: str | None) -> str | None:
    """Liefert einen deutschen Warntext, wenn Kategorie und Kundenland nicht
    zusammenpassen, sonst None. Ohne Kundenland (None oder leer) immer None.

    Die Kategorien S (Inlandssteuer) und E (Kleinunternehmer) hängen nicht vom
    Land des Kunden ab und warnen nie.
    """
    land = (kundenland or "").strip().upper()
    if not land:
        return None
    if land == "DE" and kategorie in {"AE", "K", "O"}:
        return _WARNUNG_INLAND
    if land != "DE" and land in EU_MITGLIEDSTAATEN and kategorie == "O":
        return _WARNUNG_EU
    if land not in EU_MITGLIEDSTAATEN and kategorie in {"AE", "K"}:
        return _WARNUNG_DRITTLAND
    return None


AE_INLAND_FREMDE_UST_ID = (
    "Reverse Charge (AE) an einen Kunden mit Land DE, dessen USt-IdNr. aus "
    "einem anderen Land stammt: Das widerspricht sich. Bitte Land und "
    "USt-IdNr. beim Kunden prüfen, speichern und die Rechnung neu finalisieren."
)


def ae_inland_mit_fremder_ust_id(
    kategorie: str | None, kundenland: str | None, ust_id: str | None,
) -> str | None:
    """Fehlertext, wenn Kategorie AE, Kundenland DE und die USt-IdNr. ein
    anderes Laenderpraefix als DE traegt; sonst None. Fehlende oder unlesbare
    USt-IdNr. gibt None (AE ohne USt-IdNr. sperrt eine andere Regel)."""
    if kategorie != "AE" or (kundenland or "").strip().upper() != "DE":
        return None
    kanonisch = normalisiere_ust_id(ust_id)
    if kanonisch and kanonisch[:2] != "DE":
        return AE_INLAND_FREMDE_UST_ID
    return None
