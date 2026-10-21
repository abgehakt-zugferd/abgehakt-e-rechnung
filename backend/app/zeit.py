"""Kalenderzeit der Anwendung: fest Europe/Berlin.

Abgehakt ist fuer deutsche E-Rechnungen gebaut. „Heute“ und „jetzt“ kommen
aus dieser einen Naht, nicht aus dem Prozessdatum des Containers (UTC) und
nicht aus einer einstellbaren Zeitzone. Tests ersetzen `_utc_jetzt`.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
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


def zeitraumgrenzen(von: date, bis: date) -> tuple[datetime, datetime]:
    """Kalenderzeitraum [von, bis] (beide einschliesslich) als halboffene
    Zeitstempelgrenzen [anfang, ende): Mitternacht des ersten Tags bis
    Mitternacht des Tags nach dem letzten, jeweils in Europe/Berlin.

    Fuer Filter auf timestamptz-Spalten: ein nacktes date wuerde Postgres
    in Mitternacht der Sitzungszone umwandeln, ein fester Offset scheitert
    am Sommer-/Winterzeitwechsel. Mitternacht wird deshalb ueber die Zone
    gebildet, nie ueber ein gerechnetes Offset. Beide Rueckgaben sind aware.
    """
    anfang = datetime(von.year, von.month, von.day, tzinfo=ZEITZONE)
    ende_tag = bis + timedelta(days=1)
    ende = datetime(ende_tag.year, ende_tag.month, ende_tag.day, tzinfo=ZEITZONE)
    return anfang, ende
