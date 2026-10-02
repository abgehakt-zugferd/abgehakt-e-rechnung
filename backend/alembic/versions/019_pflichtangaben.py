"""Pflichtangaben auf Geschäftsbriefen an company

Revision ID: 019
Revises: 018
Create Date: 2026-10-02

§ 35a GmbHG, § 80 AktG, §§ 37a, 125a HGB: Rechtsform, Sitz, Registergericht,
Registernummer und Vertretung gehören auf jede Rechnung. Bestand bleibt leer;
die Migration rät keine Rechtsform. Ohne gewählte Rechtsform sperrt der
Validator das Stellen, bis sie in den Einstellungen nachgetragen ist.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SPALTEN = (
    ("rechtsform", 20),
    ("sitz", 100),
    ("registergericht", 100),
    ("registernummer", 50),
    ("vertretung", 500),
    ("aufsichtsrat_vorsitz", 255),
)


def upgrade() -> None:
    for name, laenge in SPALTEN:
        op.add_column("company", sa.Column(name, sa.String(laenge), nullable=True))


def downgrade() -> None:
    for name, _ in reversed(SPALTEN):
        op.drop_column("company", name)
