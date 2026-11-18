"""Ob ein fehlendes Mustang-JAR ein Fehler ist (MUSTANG_ERWARTET)."""

_WAHR = {"1", "true", "yes", "ja"}


def jar_fehlt_obwohl_erwartet(umgebung, *, jar_da: bool) -> str | None:
    """Meldung, wenn die Umgebung das JAR erwartet und es fehlt, sonst None."""
    if jar_da or str(umgebung.get("MUSTANG_ERWARTET", "")).strip().lower() not in _WAHR:
        return None
    return ("MUSTANG_ERWARTET ist gesetzt, aber das Mustang-JAR fehlt: die Mustang-Tests "
            "würden still übersprungen. Abbild neu bauen oder die Variable weglassen.")
