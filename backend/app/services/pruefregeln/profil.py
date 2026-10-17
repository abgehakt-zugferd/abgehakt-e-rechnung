"""ZUGFeRD-Profil (§ 14 UStG): nur EN16931-konforme Profile sind E-Rechnungen."""
from app.services.pruefregeln.befund import Issue
from app.services.pruefregeln.kontext import Pruefkontext
from app.services.zugferd_xml import COMPLIANT_PROFILES


def pruefe_profil(kontext: Pruefkontext) -> list[Issue]:
    invoice = kontext.invoice
    # ZUGFeRD-Profil muss EN16931-konform sein (§ 14 UStG). MINIMUM/BASIC-WL sind
    # nicht rechtskonform und werden NICHT als E-Rechnung akzeptiert (#98 E4) —
    # harter Fehler, damit das Finalize-Gate fail-closed 400 statt 500 liefert.
    # None/leer = Modell-Default EN16931 (Spalte nullable=False) → kein Fehler.
    if (invoice.zugferd_profile or "EN16931") not in COMPLIANT_PROFILES:
        return [Issue(
            "PROFILE_NOT_COMPLIANT", "error",
            f"ZUGFeRD-Profil '{invoice.zugferd_profile}' ist als E-Rechnung unzulässig "
            f"(mind. EN16931 erforderlich; MINIMUM/BASIC-WL sind nicht rechtskonform). "
            f"Erlaubt: {', '.join(sorted(COMPLIANT_PROFILES))}.",
            "zugferd_profile",
        )]
    return []
