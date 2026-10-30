"""Schlussrechnung: verrechnete Anzahlungen (BT-113, BG-3)

Revision ID: 033
Revises: 032
Create Date: 2026-10-30

Eigene Tabelle statt einer Spalte an der Anzahlung: gestellte Belege sind
unveraenderlich (GoBD), die Verknuepfung muss sich aber loesen koennen, wenn
die Schlussrechnung aufgehoben wird. Der partielle Unique-Index sichert, dass
ein Beleg hoechstens einmal aktiv verrechnet ist. Bestand bleibt leer.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "033"
down_revision: Union[str, None] = "032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "anzahlung_verrechnungen",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("schlussrechnung_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("anzahlung_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("aktiv", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.ForeignKeyConstraint(["schlussrechnung_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["anzahlung_id"], ["invoices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("schlussrechnung_id", "anzahlung_id", name="uq_anzahlung_verrechnung_paar"),
    )
    op.create_index(
        "ix_anzahlung_verrechnungen_schlussrechnung_id", "anzahlung_verrechnungen",
        ["schlussrechnung_id"],
    )
    op.create_index(
        "uq_anzahlung_nur_einmal_aktiv", "anzahlung_verrechnungen", ["anzahlung_id"],
        unique=True, postgresql_where=sa.text("aktiv"),
    )


def downgrade() -> None:
    op.drop_index("uq_anzahlung_nur_einmal_aktiv", table_name="anzahlung_verrechnungen")
    op.drop_index("ix_anzahlung_verrechnungen_schlussrechnung_id", table_name="anzahlung_verrechnungen")
    op.drop_table("anzahlung_verrechnungen")
