"""Ersatzrechnung: Bezug auf die stornierte Rechnung (BT-25) an invoices

Revision ID: 022
Revises: 021
Create Date: 2026-10-08

Eigene Spalte neben original_invoice_id (docs/specs/ersatzrechnung.md). Bestand bleibt leer.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column("ersetzt_invoice_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "invoices_ersetzt_invoice_id_fkey", "invoices", "invoices",
        ["ersetzt_invoice_id"], ["id"],
    )
    op.create_index(
        "ix_invoices_ersetzt_invoice_id", "invoices", ["ersetzt_invoice_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_invoices_ersetzt_invoice_id", table_name="invoices")
    op.drop_constraint("invoices_ersetzt_invoice_id_fkey", "invoices", type_="foreignkey")
    op.drop_column("invoices", "ersetzt_invoice_id")
