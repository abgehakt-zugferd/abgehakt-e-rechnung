"""Unit-Tests für die Audit-Serialisierung (reine Funktionen, keine DB)."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.services.audit import to_jsonable, snapshot
from app.models.customer import Customer


def test_to_jsonable_converts_non_json_types():
    assert to_jsonable(Decimal("1190.00")) == "1190.00"
    assert to_jsonable(date(2026, 7, 8)) == "2026-07-08"
    assert to_jsonable(datetime(2026, 7, 8, 12, 30, tzinfo=timezone.utc)) == "2026-07-08T12:30:00+00:00"
    u = uuid.uuid4()
    assert to_jsonable(u) == str(u)


def test_to_jsonable_passes_json_native_types_through():
    assert to_jsonable("text") == "text"
    assert to_jsonable(42) == 42
    assert to_jsonable(True) is True
    assert to_jsonable(None) is None


def test_snapshot_contains_all_columns_and_is_json_ready():
    c = Customer(
        customer_number="K-2026-001", name="Test GmbH",
        address_line1="Weg 1", zip_code="12345", city="Musterstadt",
    )
    c.id = uuid.uuid4()
    snap = snapshot(c)
    assert snap["customer_number"] == "K-2026-001"
    assert snap["id"] == str(c.id)          # UUID → str
    assert snap["deleted_at"] is None       # nullable Spalte enthalten
    assert "invoices" not in snap           # Relationship NICHT enthalten
