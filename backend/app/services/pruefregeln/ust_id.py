"""VIES-Pruefstand einer USt-IdNr., gemeinsam fuer Firma (SELLER) und Kunde (BUYER).

War zuvor _ust_id_validator_issues in validator.py; die Logik ist unveraendert,
sammelt aber in einer Liste statt in zwei.
"""
from app.services.pruefregeln.befund import Issue
from app.services.ust_id_pruefung import vies_name_vergleichbar


def ust_id_befunde(entity, prefix: str, field: str) -> list[Issue]:
    """VIES-Pruefstand aus Kunde/Firma in Validator-Meldungen."""
    checked = getattr(entity, "vat_id_checked_at", None)
    valid = getattr(entity, "vat_id_check_valid", None)
    name_match = getattr(entity, "vat_id_name_match", None)
    if not checked:
        return [Issue(
            f"{prefix}_VAT_ID_NOT_CHECKED", "warning",
            "Eigene USt-IdNr. in den Einstellungen wurde noch nicht bei VIES geprueft."
            if prefix == "SELLER" else
            "USt-IdNr. des Kunden wurde noch nicht bei VIES geprueft.",
            field,
        )]
    if valid is None:
        return [Issue(
            f"{prefix}_VAT_ID_VIES_UNAVAILABLE", "warning",
            "VIES war beim letzten Pruefversuch nicht erreichbar; Gueltigkeit unbekannt.",
            field,
        )]
    befunde: list[Issue] = []
    if valid is False:
        befunde.append(Issue(
            f"{prefix}_VAT_ID_VIES_INVALID", "error",
            "USt-IdNr. ist bei VIES als ungueltig oder nicht registriert gemeldet.",
            field,
        ))
    if name_match == "weicht_ab":
        stammname = (getattr(entity, "name", None) or "").strip()
        vies_name = vies_name_vergleichbar(getattr(entity, "vat_id_vies_name", None))
        if not stammname or not vies_name:
            return befunde
        befunde.append(Issue(
            f"{prefix}_VAT_ID_NAME_MISMATCH", "warning",
            "Der bei VIES registrierte Firmenname weicht vom Namen in den Einstellungen ab."
            if prefix == "SELLER" else
            "Der bei VIES registrierte Name weicht vom Kundennamen ab.",
            field,
        ))
    return befunde
