"""Abzug auf Belegebene (EN 16931 BG-20) an invoices

Revision ID: 023
Revises: 022
Create Date: 2026-10-15

Zwei Spalten, immer als Paar: kein Abzug (beide NULL) oder Betrag > 0 mit Grund
(BR-33). Bestand bleibt leer. Identisch zum Modell (tests/test_migrationskette.py).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("abzug_betrag", sa.Numeric(12, 2), nullable=True))
    op.add_column("invoices", sa.Column("abzug_grund", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_invoices_abzug_beide_oder_gueltig", "invoices",
        "(abzug_betrag IS NULL AND abzug_grund IS NULL) "
        "OR (abzug_betrag > 0 AND abzug_grund IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_invoices_abzug_beide_oder_gueltig", "invoices", type_="check")
    op.drop_column("invoices", "abzug_grund")
    op.drop_column("invoices", "abzug_betrag")
