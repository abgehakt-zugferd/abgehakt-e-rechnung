"""VIES-Pruefstand fuer USt-IdNr. (Kunde und Firma)

Speichert Ergebnis der letzten VIES-Abfrage: gueltig, registrierter Name, Name-Abgleich.

Revision ID: 008
Revises: 007
Create Date: 2026-09-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SPALTEN = (
    ("vat_id_checked_at", sa.DateTime(timezone=True)),
    ("vat_id_check_valid", sa.Boolean()),
    ("vat_id_vies_name", sa.String(length=500)),
    ("vat_id_name_match", sa.String(length=20)),
)


def upgrade() -> None:
    for spalte, typ in _SPALTEN:
        op.add_column("customers", sa.Column(spalte, typ, nullable=True))
    for spalte, typ in _SPALTEN:
        op.add_column("company", sa.Column(spalte, typ, nullable=True))


def downgrade() -> None:
    for spalte, _ in reversed(_SPALTEN):
        op.drop_column("company", spalte)
    for spalte, _ in reversed(_SPALTEN):
        op.drop_column("customers", spalte)
