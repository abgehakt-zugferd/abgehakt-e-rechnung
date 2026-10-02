"""Leistungszeitraum je Position (BT-134/135) an invoice_items

Revision ID: 021
Revises: 020
Create Date: 2026-10-02

Optional, beide oder keiner, von <= bis. Bestand bleibt leer. Der Kopfzeitraum
der Rechnung bleibt die Pflichtangabe; diese Spalten schlüsseln ihn nur auf.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoice_items", sa.Column("leistung_von", sa.Date(), nullable=True))
    op.add_column("invoice_items", sa.Column("leistung_bis", sa.Date(), nullable=True))
    op.create_check_constraint(
        "ck_invoice_items_leistung_beide_oder_keiner", "invoice_items",
        "(leistung_von IS NULL) = (leistung_bis IS NULL)",
    )
    op.create_check_constraint(
        "ck_invoice_items_leistung_reihenfolge", "invoice_items",
        "leistung_von IS NULL OR leistung_von <= leistung_bis",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invoice_items_leistung_reihenfolge", "invoice_items", type_="check")
    op.drop_constraint("ck_invoice_items_leistung_beide_oder_keiner", "invoice_items", type_="check")
    op.drop_column("invoice_items", "leistung_bis")
    op.drop_column("invoice_items", "leistung_von")
