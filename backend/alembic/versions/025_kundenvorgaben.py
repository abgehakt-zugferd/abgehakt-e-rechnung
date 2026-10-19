"""Kundenvorgaben am Kunden, kopiert in den Beleg (Bauschritt 2a, Festlegung 15).

Die Vorgaben werden beim Anlegen KOPIERT, nicht live gelesen: eine spaetere
Aenderung am Kunden darf keinen bestehenden Beleg erreichen. Deshalb stehen
kopftext/fusstext auch als eigene Spalten an der Rechnung, nicht als Verweis.
"""
import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade():
    # Steuervorgabe fuer Rechnungen aus Rechnungsauftraegen (Festlegung 13):
    # Wertevorrat {"AE"}; NULL heisst keine Vorgabe. Der CHECK ist die zweite
    # Verteidigungslinie hinter der Formularpruefung.
    op.add_column("customers", sa.Column("auftrag_steuer", sa.String(20), nullable=True))
    op.create_check_constraint(
        "ck_customers_auftrag_steuer_wertevorrat",
        "customers",
        "auftrag_steuer IS NULL OR auftrag_steuer IN ('AE')",
    )
    op.add_column("customers", sa.Column("kopftext", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("fusstext", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("zahlungshinweis", sa.Text(), nullable=True))
    op.add_column("customers", sa.Column("belegsprache_vorgabe", sa.String(2), nullable=True))
    op.create_check_constraint(
        "ck_customers_belegsprache_vorgabe_wertevorrat",
        "customers",
        "belegsprache_vorgabe IS NULL OR belegsprache_vorgabe IN ('de', 'en')",
    )
    op.add_column("invoices", sa.Column("kopftext", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("fusstext", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("invoices", "fusstext")
    op.drop_column("invoices", "kopftext")
    op.drop_constraint("ck_customers_belegsprache_vorgabe_wertevorrat", "customers", type_="check")
    op.drop_column("customers", "belegsprache_vorgabe")
    op.drop_column("customers", "zahlungshinweis")
    op.drop_column("customers", "fusstext")
    op.drop_column("customers", "kopftext")
    op.drop_constraint("ck_customers_auftrag_steuer_wertevorrat", "customers", type_="check")
    op.drop_column("customers", "auftrag_steuer")
