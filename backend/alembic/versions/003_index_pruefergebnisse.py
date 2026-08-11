"""Index auf validation_results (invoice_id, validated_at)

Die Rechnungs-Detailseite liest immer dasselbe: das juengste Pruefergebnis zu
EINER Rechnung. Ohne Index laeuft das ueber die ganze Tabelle, und die waechst
bei jedem Klick auf "pruefen" und wird nie aufgeraeumt.

Revision ID: 003
Revises: 002
Create Date: 2026-08-09

"""
from typing import Sequence, Union

from alembic import op


revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index('ix_validation_results_invoice_zeit', 'validation_results',
                    ['invoice_id', 'validated_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_validation_results_invoice_zeit',
                  table_name='validation_results')
