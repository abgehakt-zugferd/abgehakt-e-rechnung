"""#179: Kalenderzeitraeume werden zu Berliner Zeitstempelgrenzen, nicht zu
Mitternacht der DB-Sitzungszone (UTC). Ein fester Offset scheitert am
Sommer-/Winterzeitwechsel — deshalb werden die Offsets selbst geprueft."""
from datetime import date, datetime, timedelta

from app.zeit import ZEITZONE, zeitraumgrenzen


def test_wintertag_liefert_mez_mitternacht():
    anfang, ende = zeitraumgrenzen(date(2026, 1, 15), date(2026, 1, 15))
    assert anfang == datetime(2026, 1, 15, 0, 0, tzinfo=ZEITZONE)
    assert ende == datetime(2026, 1, 16, 0, 0, tzinfo=ZEITZONE)
    assert anfang.utcoffset() == timedelta(hours=1)
    assert ende.utcoffset() == timedelta(hours=1)


def test_sommertag_liefert_mesz_mitternacht():
    anfang, ende = zeitraumgrenzen(date(2026, 7, 15), date(2026, 7, 15))
    assert anfang == datetime(2026, 7, 15, 0, 0, tzinfo=ZEITZONE)
    assert ende == datetime(2026, 7, 16, 0, 0, tzinfo=ZEITZONE)
    assert anfang.utcoffset() == timedelta(hours=2)
    assert ende.utcoffset() == timedelta(hours=2)


def test_zeitraum_ueber_sommerzeitbeginn_wechselt_den_offset():
    """Letzter Sonntag im Maerz 2026 ist der 29.03.: davor MEZ, danach MESZ."""
    anfang, ende = zeitraumgrenzen(date(2026, 3, 28), date(2026, 3, 30))
    assert anfang == datetime(2026, 3, 28, 0, 0, tzinfo=ZEITZONE)
    assert ende == datetime(2026, 3, 31, 0, 0, tzinfo=ZEITZONE)
    assert anfang.utcoffset() == timedelta(hours=1)
    assert ende.utcoffset() == timedelta(hours=2)


def test_zeitraum_ueber_winterzeitbeginn_wechselt_den_offset():
    """Letzter Sonntag im Oktober 2026 ist der 25.10.: davor MESZ, danach MEZ."""
    anfang, ende = zeitraumgrenzen(date(2026, 10, 24), date(2026, 10, 26))
    assert anfang == datetime(2026, 10, 24, 0, 0, tzinfo=ZEITZONE)
    assert ende == datetime(2026, 10, 27, 0, 0, tzinfo=ZEITZONE)
    assert anfang.utcoffset() == timedelta(hours=2)
    assert ende.utcoffset() == timedelta(hours=1)


def test_grenzen_sind_aware():
    """Naive Grenzen wuerden den Vergleich wieder der Sitzungszone ueberlassen."""
    for grenze in zeitraumgrenzen(date(2026, 3, 1), date(2026, 3, 31)):
        assert grenze.tzinfo is not None
        assert grenze.utcoffset() is not None
