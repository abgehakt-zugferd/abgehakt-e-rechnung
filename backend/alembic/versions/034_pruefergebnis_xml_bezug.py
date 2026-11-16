"""Prüfergebnis: Bezug auf das geprüfte XML und Bestätigung trotz Warnung

Revision ID: 034
Revises: 033
Create Date: 2026-11-16

Ein Prüfergebnis ist eine Momentaufnahme. `xml_sha256` bindet es an genau das
geprüfte XML; `anlass` unterscheidet die Prüfung beim Finalisieren von einer
Prüfung auf Knopfdruck. Wurde trotz Mustang-Warnung finalisiert, stehen die
übergangenen Regelkennungen und der Zeitpunkt der Bestätigung dabei. Bestand
bleibt leer (NULL = keine Angabe).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "034"
down_revision: Union[str, None] = "033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("validation_results", sa.Column("xml_sha256", sa.String(64), nullable=True))
    op.add_column("validation_results", sa.Column("anlass", sa.String(20), nullable=True))
    op.add_column("validation_results", sa.Column("bestaetigte_regeln", sa.JSON(), nullable=True))
    op.add_column("validation_results", sa.Column("bestaetigt_am", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("validation_results", "bestaetigt_am")
    op.drop_column("validation_results", "bestaetigte_regeln")
    op.drop_column("validation_results", "anlass")
    op.drop_column("validation_results", "xml_sha256")
