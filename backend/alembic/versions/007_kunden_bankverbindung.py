"""Bankverbindung je Kunde (IBAN, BIC, Bank) fuer Gutschrift-Auszahlungen

Abrechnungsgutschriften (389) und andere Gutschriften brauchen die Empfaenger-IBAN
auf dem Beleg und im EPC-QR fuer die Ueberweisung an den Beteiligten.

Revision ID: 007
Revises: 006
Create Date: 2026-09-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("bank_iban", sa.String(length=34), nullable=True))
    op.add_column("customers", sa.Column("bank_bic", sa.String(length=11), nullable=True))
    op.add_column("customers", sa.Column("bank_name", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "bank_name")
    op.drop_column("customers", "bank_bic")
    op.drop_column("customers", "bank_iban")
