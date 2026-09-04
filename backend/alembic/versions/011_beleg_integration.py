"""Beleg-Integration: Schalter, Verarbeitungsgedaechtnis, Belegbezug an der Rechnung

Revision ID: 011
Revises: 010
Create Date: 2026-09-03

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Der Schalter. `server_default="false"` ist die Zusage an jede
    # Bestandsinstallation: nach dem Update ist nichts anders als vorher.
    op.add_column(
        "app_config",
        sa.Column("beleg_integration_aktiv", sa.Boolean(), nullable=False,
                  server_default="false"),
    )

    # Nur ANGENOMMENE Belege. Beide Kennzeichen eindeutig: dieselbe Kennung mit
    # anderem Inhalt ist ein Widerspruch und keine Wiedervorlage.
    op.create_table(
        "uebergabe_eingaenge",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("beleg_id", sa.String(64), nullable=False, unique=True),
        sa.Column("beleg_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("absender", sa.String(64), nullable=False, index=True),
        sa.Column("nutzlast_art", sa.String(32), nullable=False),
        sa.Column("erzeugt_am", sa.DateTime(timezone=True), nullable=False),
        sa.Column("angenommen_am", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("dateiname", sa.String(255)),
    )

    op.add_column("invoices", sa.Column("uebergabe_beleg_id", sa.String(64)))
    op.add_column("invoices", sa.Column("uebergabe_beleg_sha256", sa.String(64)))


def downgrade() -> None:
    op.drop_column("invoices", "uebergabe_beleg_sha256")
    op.drop_column("invoices", "uebergabe_beleg_id")
    op.drop_table("uebergabe_eingaenge")
    op.drop_column("app_config", "beleg_integration_aktiv")
