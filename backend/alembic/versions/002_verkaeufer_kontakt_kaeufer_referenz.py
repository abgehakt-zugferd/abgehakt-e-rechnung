"""Verkaeuferkontakt (BT-41) und Kaeuferreferenz (BT-10)

Beide Angaben schliessen Beanstandungen aus dem XRechnung-CIUS (#153): BR-DE-2
verlangt einen Ansprechpartner beim Verkaeufer, BR-DE-15 eine Referenz des
Kaeufers. Beide sind nullable: sie sind nach EN 16931 nicht verpflichtend, und
eine bestehende Installation soll ohne Nacharbeit weiterlaufen.

Revision ID: 002
Revises: 001
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('company', sa.Column('contact_name', sa.String(length=255), nullable=True))
    op.add_column('invoices', sa.Column('buyer_reference', sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column('invoices', 'buyer_reference')
    op.drop_column('company', 'contact_name')
