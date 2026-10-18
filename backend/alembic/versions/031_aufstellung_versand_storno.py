"""Versandnachweis und hoechstens ein aktives Storno je Aufstellung."""
import sqlalchemy as sa
from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None

INDEX = "uq_aufstellungen_ein_aktives_storno_pro_original"
WHERE = "status <> 'discarded' AND storniert_id IS NOT NULL"


def upgrade():
    # Der Unique-Index bricht bei doppeltem Bestand ab. Keine automatische
    # Bereinigung: Auch eine Stornozeile ist ein aufzubewahrender Nachweis.
    op.create_index(INDEX, "aufstellungen", ["storniert_id"], unique=True,
                    postgresql_where=sa.text(WHERE))
    op.create_table(
        "aufstellung_send_logs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("aufstellung_id", sa.UUID(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("to_email", sa.String(255), nullable=False),
        sa.Column("ziel", sa.Text(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.CheckConstraint("ziel = 'buchhaltung'", name="ck_aufstellung_send_logs_ziel"),
        sa.ForeignKeyConstraint(["aufstellung_id"], ["aufstellungen.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_aufstellung_send_logs_aufstellung_id", "aufstellung_send_logs",
                    ["aufstellung_id"])


def downgrade():
    op.drop_table("aufstellung_send_logs")
    op.drop_index(INDEX, table_name="aufstellungen")
