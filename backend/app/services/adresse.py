"""Hilfen fuer Adresszeilen auf Belegen und in der XML."""


def bereinige_adresszeile2(name: str | None, line2: str | None) -> str | None:
    """Adresszeile 2 nur wenn gesetzt und nicht identisch mit dem Namen.

    In der Praxis wird der Firmenname manchmal versehentlich in Zeile 2
    wiederholt (Setup/Einstellungen). Das erzeugt im PDF-Header und in der
    CII-XML einen sichtbaren Doppelnamen.
    """
    if not line2:
        return None
    line2 = line2.strip()
    if not line2:
        return None
    if name and line2.casefold() == name.strip().casefold():
        return None
    return line2
