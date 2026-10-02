"""Artikelnummer (BT-155) an invoice_items

Revision ID: 020
Revises: 019
Create Date: 2026-10-02

Optionale eigene Artikel- oder Leistungsnummer je Position. Bestand bleibt leer.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoice_items", sa.Column("artikelnummer", sa.String(50), nullable=True))


def downgrade() -> None:
    op.drop_column("invoice_items", "artikelnummer")
