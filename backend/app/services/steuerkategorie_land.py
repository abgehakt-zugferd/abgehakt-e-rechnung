"""Plausibilitätsprüfung: passt die gewählte Steuerkategorie zum Kundenland? (#145)

Das ist eine Plausibilitätswarnung und keine Steuerberatung: die Regeln nennen
den Normalfall, im Einzelfall können Abweichungen zulässig sein. Deshalb wird
nie ein harter Fehler ausgelöst, sondern nur ein Text zurückgegeben, den der
Validator als Warnung anzeigt.

Die Funktion liefert bewusst KEIN Issue-Objekt zurück: Issue ist in
validator.py definiert, und validator.py importiert dieses Modul. Ein
Rückimport wäre ein Zirkelbezug.
"""
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
