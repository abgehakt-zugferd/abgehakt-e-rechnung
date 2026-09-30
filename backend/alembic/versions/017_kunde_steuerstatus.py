"""Gutschriftempfaenger, ungeklaerter Steuerstatus, Steuernummer am Kunden

Revision ID: 017
Revises: 016
Create Date: 2026-09-30

Der Steuerstatus war bisher still auf regelbesteuert gesetzt, ohne dass jemand
gefragt wurde. Ab jetzt ist die Voreinstellung ungeklaert; nur
Gutschriftempfaenger brauchen einen geklaerten Wert vor dem Finalisieren einer
389. Bestandskunden mit bereits angelegter Honorargutschrift werden als
Gutschriftempfaenger markiert.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column(
            "gutschriftempfaenger",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    op.add_column(
        "customers",
        sa.Column("tax_number", sa.String(length=50), nullable=True),
    )
    op.add_column(
        "customers",
        sa.Column("ust_status_bestaetigt_am", sa.Date(), nullable=True),
    )
    op.alter_column(
        "customers",
        "ust_status",
        existing_type=sa.String(length=20),
        server_default="ungeklaert",
        existing_nullable=False,
    )
    op.execute("UPDATE customers SET ust_status = 'ungeklaert'")
    op.execute(
        """
        UPDATE customers SET gutschriftempfaenger = true
        WHERE id IN (
            SELECT DISTINCT customer_id FROM invoices
            WHERE invoice_type = 'self_billing' AND customer_id IS NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute(
        "UPDATE customers SET ust_status = 'regelbesteuert' "
        "WHERE ust_status = 'ungeklaert'"
    )
    op.alter_column(
        "customers",
        "ust_status",
        existing_type=sa.String(length=20),
        server_default="regelbesteuert",
        existing_nullable=False,
    )
    op.drop_column("customers", "ust_status_bestaetigt_am")
    op.drop_column("customers", "tax_number")
    op.drop_column("customers", "gutschriftempfaenger")
