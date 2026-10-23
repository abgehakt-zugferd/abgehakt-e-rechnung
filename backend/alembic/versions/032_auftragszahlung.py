"""Offene Kundenvorgabe am unfertigen Rechnungsauftrag erlauben.

Mit --autogenerate erzeugt. Alembic erkennt Änderungen an CHECK-Ausdrücken
nicht; deshalb ist der Austausch ausdrücklich ergänzt und gegen Postgres
getestet. Fertige Belege und manuelle Entwürfe behalten die bisherige Grenze.
"""
from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None

NAME = "ck_invoices_faelligkeit_oder_bedingungen"
BISHER = "due_date IS NOT NULL OR (payment_terms IS NOT NULL AND payment_terms <> '')"
OFFENER_AUFTRAG = (
    "status IN ('draft', 'discarded') AND auftragsschluessel IS NOT NULL "
    "AND uebergabe_beleg_sha256 IS NOT NULL AND invoice_type IS NULL"
)


def upgrade():
    op.drop_constraint(NAME, "invoices", type_="check")
    op.create_check_constraint(NAME, "invoices", f"{BISHER} OR ({OFFENER_AUFTRAG})")


def downgrade():
    # Ein offener Auftrag ohne Vorgabe verhindert den Rückweg. Keine erfundene
    # Frist nachtragen: Der Betreiber muss solche Entwürfe vorher vervollständigen.
    op.drop_constraint(NAME, "invoices", type_="check")
    op.create_check_constraint(NAME, "invoices", BISHER)
