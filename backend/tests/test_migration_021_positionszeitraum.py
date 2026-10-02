"""Migration 021: die Zeitraum-Constraints stehen auch in der migrierten Datenbank.

`test_migrationskette.py` vergleicht Spalten, aber Alembic vergleicht keine
CHECK-Constraints. Ohne diesen Test fiele eine Migration ohne Constraint nicht auf,
weil die übrigen Tests ihr Schema aus den Modellen bauen.
"""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.test_migrationskette import migrationsdatenbank  # noqa: F401


def test_migrierte_datenbank_lehnt_halben_positionszeitraum_ab(migrationsdatenbank):  # noqa: F811
    url, _ = migrationsdatenbank
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            namen = set(conn.execute(text(
                "SELECT conname FROM pg_constraint WHERE conrelid = 'invoice_items'::regclass"
            )).scalars())
            assert {"ck_invoice_items_leistung_beide_oder_keiner",
                    "ck_invoice_items_leistung_reihenfolge"} <= namen
            with pytest.raises(IntegrityError):
                conn.execute(text(
                    "INSERT INTO invoice_items (invoice_id, position, description, unit, quantity, "
                    "unit_price, tax_rate, net_amount, tax_amount, gross_amount, leistung_von) "
                    "VALUES (gen_random_uuid(), 1, 'Abo', 'Stück', 1, 1, 0, 1, 0, 1, '2026-07-01')"
                ))
    finally:
        engine.dispose()
