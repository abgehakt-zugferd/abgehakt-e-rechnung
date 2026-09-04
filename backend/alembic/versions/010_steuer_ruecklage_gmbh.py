"""Steuer-Ruecklage fuer GmbH in den Firmeneinstellungen

Revision ID: 010
Revises: 009
Create Date: 2026-09-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "company",
        sa.Column("kst_satz_percent", sa.Numeric(5, 2), nullable=False, server_default="15.00"),
    )
    op.add_column(
        "company",
        sa.Column("soli_auf_kst_percent", sa.Numeric(5, 2), nullable=False, server_default="5.50"),
    )
    op.add_column(
        "company",
        sa.Column("gewerbe_hebesatz", sa.Integer(), nullable=False, server_default="400"),
    )


def downgrade() -> None:
    op.drop_column("company", "gewerbe_hebesatz")
    op.drop_column("company", "soli_auf_kst_percent")
    op.drop_column("company", "kst_satz_percent")
