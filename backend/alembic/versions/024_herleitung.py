"""Herleitung je Position, beide Werte oder keiner."""
import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("invoice_items", sa.Column("basis_netto", sa.Numeric(12, 2), nullable=True))
    op.add_column("invoice_items", sa.Column("satz", sa.Numeric(5, 2), nullable=True))
    op.create_check_constraint("ck_invoice_items_herleitung_beide_oder_keine",
        "invoice_items", "(basis_netto IS NULL) = (satz IS NULL)")


def downgrade():
    op.drop_constraint("ck_invoice_items_herleitung_beide_oder_keine", "invoice_items", type_="check")
    op.drop_column("invoice_items", "satz")
    op.drop_column("invoice_items", "basis_netto")
