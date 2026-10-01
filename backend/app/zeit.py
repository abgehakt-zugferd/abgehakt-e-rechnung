"""Kalenderzeit der Anwendung: fest Europe/Berlin.

Abgehakt ist fuer deutsche E-Rechnungen gebaut. „Heute“ und „jetzt“ kommen
aus dieser einen Naht, nicht aus dem Prozessdatum des Containers (UTC) und
nicht aus einer einstellbaren Zeitzone. Tests ersetzen `_utc_jetzt`.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

ZEITZONE = ZoneInfo("Europe/Berlin")


def _utc_jetzt() -> datetime:
    """Systemgrenze: liest die Uhr. Tests ersetzen diese Funktion."""
    return datetime.now(timezone.utc)


def jetzt() -> datetime:
    """Aktueller Zeitpunkt als aware datetime in Europe/Berlin."""
    return _utc_jetzt().astimezone(ZEITZONE)


def heute() -> date:
    """Kalendertag in Europe/Berlin."""
    return jetzt().date()


def kalendertag(ts: datetime) -> date:
    """Kalendertag eines aware Zeitstempels in Europe/Berlin.

    Naive Zeitstempel werden abgelehnt: ohne Offset ist die Umrechnung
    nach Berlin nicht definiert.
    """
    if ts.tzinfo is None:
        raise ValueError("kalendertag verlangt einen aware Zeitstempel.")
    return ts.astimezone(ZEITZONE).date()
