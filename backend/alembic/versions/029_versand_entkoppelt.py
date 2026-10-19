"""Versand an Buchhaltung und Kunde entkoppelt (Bauschritt 5a, Entscheidung 6).

Bisher war der Versand EIN Schritt: Mail an den Kunden, Blindkopie an die
Upload-Adresse, und `invoices.datev_sent_at` hielt den Zeitpunkt fuer beides.
Ab hier zaehlt `datev_sent_at` nur noch fuer die Buchhaltung; der Kunde hat
den eigenen Vermerk `kunde_zugestellt_am`. Fuer den Bestand gilt: Der bisherige
Versand tat beides in einem Schritt, deshalb ist `kunde_zugestellt_am =
datev_sent_at` die einzige Rueckuebersetzung, die keinen Zustellnachweis
verlorengeht.

Am Versandprotokoll kommt der Weg dazu (`ziel`) und Platz fuer eine Notiz zum
Weg (`weg_notiz`), denn drei Wege muessen sich unterscheiden lassen: der
kombinierte Standardversand, der Gang nur an die Buchhaltung und (Teil 5b) der
Freitext-Vermerk einer Zustellung ohne Mail. `to_email` wird nullable: Nur der
Freitext-Vermerk traegt keinen Empfaenger, jeder Mail-Weg muss einen nennen.
"""
import sqlalchemy as sa
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None

ZIEL_CHECK = "ck_invoice_send_log_ziel"
EMPFAENGER_CHECK = "ck_invoice_send_log_empfaenger_ausser_vermerk"


def upgrade():
    op.add_column(
        "invoices", sa.Column("kunde_zugestellt_am", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute("UPDATE invoices SET kunde_zugestellt_am = datev_sent_at")

    # server_default nur fuer den Bestand: Er fuellt alte Zeilen mit dem Weg,
    # den sie tatsächlich gegangen sind, und fällt danach weg, damit künftige
    # Zeilen ihr ziel aus dem Code mitbringen (kein stiller Füllwert, L216).
    op.add_column(
        "invoice_send_log",
        sa.Column("ziel", sa.Text(), nullable=False, server_default="kunde_und_buchhaltung"),
    )
    op.alter_column("invoice_send_log", "ziel", server_default=None)
    op.add_column("invoice_send_log", sa.Column("weg_notiz", sa.Text(), nullable=True))
    op.alter_column(
        "invoice_send_log", "to_email", existing_type=sa.String(255), nullable=True
    )
    op.create_check_constraint(
        ZIEL_CHECK,
        "invoice_send_log",
        "ziel IN ('kunde_und_buchhaltung', 'buchhaltung', 'kunde_vermerk')",
    )
    op.create_check_constraint(
        EMPFAENGER_CHECK,
        "invoice_send_log",
        "ziel = 'kunde_vermerk' OR to_email IS NOT NULL",
    )


def downgrade():
    # Bewusst ohne Ruecksicht auf kunde_vermerk-Zeilen: Sie lassen sich nicht
    # ohne Empfaenger zurueckuebersetzen, und der NOT-NULL-Wechsel schlaegt
    # dann zu, statt sie still zu verfaelschen.
    op.alter_column(
        "invoice_send_log", "to_email", existing_type=sa.String(255), nullable=False
    )
    op.drop_constraint(EMPFAENGER_CHECK, "invoice_send_log")
    op.drop_constraint(ZIEL_CHECK, "invoice_send_log")
    op.drop_column("invoice_send_log", "weg_notiz")
    op.drop_column("invoice_send_log", "ziel")
    op.drop_column("invoices", "kunde_zugestellt_am")
