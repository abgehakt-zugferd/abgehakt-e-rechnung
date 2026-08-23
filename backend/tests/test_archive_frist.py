"""#17: Jahresendprinzip fuer archive_until (§ 147 Abs. 4 AO)."""
from datetime import date

from app.services.archive_frist import berechne_archive_until


def test_jahresende_statt_kalenderdatum():
    assert berechne_archive_until(date(2026, 3, 15)) == date(2034, 12, 31)


def test_schalttag_ausstellung_ohne_value_error():
    assert berechne_archive_until(date(2092, 2, 29)) == date(2100, 12, 31)
