"""Positionsgruppe an invoice_items (Bauschritt 3, Entscheidung 3).

Freier Anzeigetext, der Positionen zu einer Gruppe ordnet (z. B. "Digital").
Nullable: eine Position ohne Gruppe ist der Normalfall. Form prueft der
Validator (POSITION_GRUPPE_GETRENNT), nicht die Spalte — der Zusammenhang
liegt ueber Zeilen, ein CHECK koennte ihn nicht ausdruecken.
"""
import sqlalchemy as sa
from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoice_items", sa.Column("gruppe", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("invoice_items", "gruppe")
