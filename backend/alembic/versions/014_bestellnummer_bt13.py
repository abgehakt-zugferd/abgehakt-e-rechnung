"""Bestellnummer des Kunden (BT-13, #101)

Eigene Spalte neben buyer_reference (BT-10): die Kaeuferreferenz traegt gegenueber
Behoerden die Leitweg-ID; die Bestellnummer / Purchase Order gehoert nach BT-13.
Beide muessen gleichzeitig moeglich sein.

Revision ID: 014
Revises: 013
Create Date: 2026-09-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("buyer_order_reference", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("invoices", "buyer_order_reference")
