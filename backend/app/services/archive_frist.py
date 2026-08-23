"""Aufbewahrungsfrist nach § 147 Abs. 4 AO / § 14b Abs. 1 UStG."""
from datetime import date


def berechne_archive_until(ausstellungsdatum: date) -> date:
    """Ende der Mindestaufbewahrung: 31.12. des (Ausstellungsjahr + 8)."""
    return date(ausstellungsdatum.year + 8, 12, 31)
