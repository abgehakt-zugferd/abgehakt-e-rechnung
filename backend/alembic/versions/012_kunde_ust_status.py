"""Umsatzsteuerlicher Status am Kunden (Gutschriftverfahren)

Revision ID: 012
Revises: 011
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `regelbesteuert` als Vorgabe: das ist der Regelfall, und fuer
    # Bestandskunden aendert sich damit nichts an bestehenden Belegen -
    # der Status wirkt erst auf neu erzeugte Gutschriften.
    op.add_column(
        "customers",
        sa.Column("ust_status", sa.String(20), nullable=False,
                  server_default="regelbesteuert"),
    )


def downgrade() -> None:
    op.drop_column("customers", "ust_status")
