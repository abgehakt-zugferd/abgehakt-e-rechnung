"""Leistungszeitraum von/bis auf Rechnungen (BG-14, BT-73/BT-74)

Revision ID: 009
Revises: 008
Create Date: 2026-09-02

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("service_period_start", sa.Date(), nullable=True))
    op.add_column("invoices", sa.Column("service_period_end", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("invoices", "service_period_end")
    op.drop_column("invoices", "service_period_start")
