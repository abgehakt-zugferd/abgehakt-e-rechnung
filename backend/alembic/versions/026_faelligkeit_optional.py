"""Fälligkeit optional, wenn ein Zahlungshinweis gilt (Bauschritt 2b).

EN 16931 BR-CO-25 verlangt bei offenem Betrag BT-9 (Fälligkeitsdatum) ODER
BT-20 (Zahlungsbedingungen). Ein Kunde, der nach eigenem Takt zahlt (z. B.
eine Plattform nach ihrem Auszahlungsbericht), bekommt kein Fälligkeitsdatum,
sondern einen Zahlungshinweis. Der CHECK ist die zweite Verteidigungslinie
hinter Formular und Validator; ein payment_terms, das nur Leerzeichen traegt,
gilt als fehlt.
"""
import sqlalchemy as sa
from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("invoices", "due_date", existing_type=sa.Date(), nullable=True)
    op.create_check_constraint(
        "ck_invoices_faelligkeit_oder_bedingungen",
        "invoices",
        "due_date IS NOT NULL OR (payment_terms IS NOT NULL AND payment_terms <> '')",
    )


def downgrade():
    # Bestehende Zeilen ohne due_date wuerden das zuruecksetzen von NOT NULL
    # scheitern lassen; wer abwaerts migriert, muss sie vorher entscheiden.
    op.drop_constraint(
        "ck_invoices_faelligkeit_oder_bedingungen", "invoices", type_="check"
    )
    op.alter_column("invoices", "due_date", existing_type=sa.Date(), nullable=False)
