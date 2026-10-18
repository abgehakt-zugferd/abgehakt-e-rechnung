"""Auftragsschluessel an invoices (Bauschritt 4a, Entscheidung 7 / Festlegung 12).

Zwei Spalten: auftragsschluessel ist der Nachweis, aus welchem Auftrag des
vorgelagerten Systems der Beleg entstand, und bleibt nach dem Finalisieren
unveraenderlich (invoice_guard). auftragsschluessel_offen traegt denselben
Wert, solange der Beleg sperrt, sonst NULL — der Status taugt nicht als
Kriterium, denn eine per Stornorechnung aufgehobene Rechnung bleibt 'issued'
oder 'paid'. Der partielle Unique-Index sichert die Zusage gegen zwei
gleichzeitige Anfragen, der CHECK bindet die Sperre an den Nachweis: Sie ist
kein zweiter, freier Wert, sondern derselbe — oder weg.
"""
import sqlalchemy as sa
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_invoices_auftragsschluessel_offen"
CHECK_NAME = "ck_invoices_auftragsschluessel_offen_wie_nachweis"


def upgrade():
    op.add_column("invoices", sa.Column("auftragsschluessel", sa.Text(), nullable=True))
    op.add_column("invoices", sa.Column("auftragsschluessel_offen", sa.Text(), nullable=True))
    op.create_index(
        INDEX_NAME,
        "invoices",
        ["auftragsschluessel_offen"],
        unique=True,
        postgresql_where=sa.text("auftragsschluessel_offen IS NOT NULL"),
    )
    op.create_check_constraint(
        CHECK_NAME,
        "invoices",
        "auftragsschluessel_offen IS NULL OR auftragsschluessel_offen = auftragsschluessel",
    )


def downgrade():
    op.drop_constraint(CHECK_NAME, "invoices")
    op.drop_index(INDEX_NAME, table_name="invoices")
    op.drop_column("invoices", "auftragsschluessel_offen")
    op.drop_column("invoices", "auftragsschluessel")
