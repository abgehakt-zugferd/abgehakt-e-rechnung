"""Migration 021: die Zeitraum-Constraints stehen auch in der migrierten Datenbank.

`test_migrationskette.py` vergleicht Spalten, aber Alembic vergleicht keine
CHECK-Constraints. Ohne diesen Test fiele eine Migration ohne Constraint nicht auf,
weil die übrigen Tests ihr Schema aus den Modellen bauen.

Die Position hängt an einer echten Rechnung: sonst scheitert der INSERT schon am
Fremdschlüssel, und der Test wäre aus dem falschen Grund grün (Gegenspieler-Review
2026-10-02). Eine gültige Position im selben Aufbau ist die Gegenprobe dafür.
"""
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests.test_migrationskette import migrationsdatenbank  # noqa: F401

_POSITION = (
    "INSERT INTO invoice_items (invoice_id, position, description, unit, quantity, "
    "unit_price, tax_rate, net_amount, tax_amount, gross_amount, leistung_von, leistung_bis) "
    "VALUES (:inv, 1, 'Abo', 'Stück', 1, 1, 0, 1, 0, 1, :von, :bis)"
)


def _rechnung(conn) -> uuid.UUID:
    kunde = uuid.uuid4()
    conn.execute(text(
        "INSERT INTO customers (id, customer_number, name, address_line1, zip_code, city) "
        "VALUES (:id, :nr, 'Probe Migration GmbH', 'Probeweg 4', '80331', 'Muenchen')"
    ), {"id": kunde, "nr": f"K-{uuid.uuid4().hex[:6]}"})
    return conn.execute(text(
        "INSERT INTO invoices (invoice_number, customer_id, issue_date, due_date, status) "
        "VALUES (:nr, :k, '2026-07-01', '2026-07-15', 'draft') RETURNING id"
    ), {"nr": f"RE-{uuid.uuid4().hex[:6]}", "k": kunde}).scalar()


@pytest.mark.parametrize("von, bis, erlaubt", [
    ("2026-07-01", "2026-07-31", True),
    ("2026-07-01", None, False),
    ("2026-07-31", "2026-07-01", False),
])
def test_migrierte_datenbank_prueft_den_positionszeitraum(migrationsdatenbank, von, bis, erlaubt):  # noqa: F811
    url, _ = migrationsdatenbank
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            trans = conn.begin()
            try:
                inv = _rechnung(conn)
                if erlaubt:
                    conn.execute(text(_POSITION), {"inv": inv, "von": von, "bis": bis})
                else:
                    with pytest.raises(IntegrityError, match="ck_invoice_items_leistung"):
                        conn.execute(text(_POSITION), {"inv": inv, "von": von, "bis": bis})
            finally:
                trans.rollback()
    finally:
        engine.dispose()
