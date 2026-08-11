"""Tests für den Kundennummern-Vorschlag: Schema JJJJMM + laufende Nr. pro Monat."""
from datetime import date
from unittest.mock import MagicMock

from app.services.customer_number import next_customer_number


def _db(numbers):
    """Fake-DB, deren Prefix-Query die übergebenen Nummern liefert."""
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [(n,) for n in numbers]
    return db


def test_first_number_of_month_starts_at_01():
    assert next_customer_number(_db([]), today=date(2026, 7, 15)) == "20260701"


def test_increments_within_same_month():
    assert next_customer_number(_db(["20260701", "20260702"]), today=date(2026, 7, 15)) == "20260703"


def test_ignores_other_months_and_legacy_numbers():
    # 20260601 (Vormonat) und KD-0001 (altes Schema) zählen nicht mit
    assert next_customer_number(_db(["KD-0001", "20260601"]), today=date(2026, 7, 15)) == "20260701"


def test_uses_max_suffix_not_count():
    # Lücken ignorieren: höchste laufende Nr. + 1, nicht Anzahl
    assert next_customer_number(_db(["20260701", "20260705"]), today=date(2026, 7, 15)) == "20260706"


def test_padding_grows_beyond_99():
    assert next_customer_number(_db(["20260799"]), today=date(2026, 7, 15)) == "202607100"
