"""Text der Rechnungsmail je Belegsprache

Vier nullable Spalten an app_config. NULL bedeutet eingebauter Text;
die Migration schreibt keine Daten.

Revision ID: 016
Revises: 015
Create Date: 2026-09-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "app_config",
        sa.Column("mail_betreff_de", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "app_config",
        sa.Column("mail_text_de", sa.Text(), nullable=True),
    )
    op.add_column(
        "app_config",
        sa.Column("mail_betreff_en", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "app_config",
        sa.Column("mail_text_en", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("app_config", "mail_text_en")
    op.drop_column("app_config", "mail_betreff_en")
    op.drop_column("app_config", "mail_text_de")
    op.drop_column("app_config", "mail_betreff_de")
