"""Zahlungsdatum bezahlt_am an invoices

Revision ID: 018
Revises: 017
Create Date: 2026-09-30

Entscheidung des Betreibers vom 2026-09-30: Umsatz ist, was bezahlt wurde.
Bestehende bezahlte Rechnungen erhalten als Naeherung das Datum von updated_at
in Europe/Berlin.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "018"
down_revision: Union[str, None] = "017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("bezahlt_am", sa.Date(), nullable=True))
    op.execute(
        """
        UPDATE invoices
        SET bezahlt_am = (updated_at AT TIME ZONE 'Europe/Berlin')::date
        WHERE status = 'paid'
        """
    )


def downgrade() -> None:
    op.drop_column("invoices", "bezahlt_am")
