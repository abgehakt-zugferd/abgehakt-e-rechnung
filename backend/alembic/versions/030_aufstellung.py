"""Abrechnungsaufstellung als eigenes Modell (Bauschritt 7a, Entscheidung 8).

Eigene Tabellen (aufstellungen, aufstellung_anlagen), eigener Nummernkreis
(aufstellung_prefix/aufstellung_counter an company), dieselben GoBD-Trigger
wie invoices: DELETE und TRUNCATE verboten. Die Aufstellung ist KEINE
Rechnung — keine Steuerspalten, kein Typcode, keine XML —, ihre Invarianten
(Summengleichung § 8b, Sperre des Auftragsschluessels nach Festlegung 12,
Hash-Form der Anlagen) stehen als CHECKs hier in der Datenbank, damit sie
auch fuer psql und Skripte gelten.

Der Unique-Index auf auftragsschluessel_offen sichert die Sperre nur INNER-
HALB dieser Tabelle gegen zwei gleichzeitige Anfragen. 'Ein Schlüssel nicht
gleichzeitig an Rechnung und Aufstellung offen' kann kein Index ausdruecken
(Postgres-Indizes leben auf je einer Tabelle); diese Zusicherung lebt in
services/auftragsschluessel.py, die beim Belegen beide Tabellen prueft.
"""
import sqlalchemy as sa
from alembic import op

from app.db.immutability_triggers import INSTALL_SQL

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("aufstellungen",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("nummer", sa.String(length=50), nullable=False),
        sa.Column("customer_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="draft", nullable=False),
        sa.Column("leistung_von", sa.Date(), nullable=False),
        sa.Column("leistung_bis", sa.Date(), nullable=False),
        sa.Column("zahlungsnummer", sa.String(length=50), nullable=False),
        sa.Column("zahlungsdatum", sa.Date(), nullable=False),
        sa.Column("waehrung", sa.String(length=3), nullable=False),
        sa.Column("brutto", sa.Numeric(12, 2), nullable=False),
        sa.Column("quellensteuer", sa.Numeric(12, 2), nullable=False),
        sa.Column("netto", sa.Numeric(12, 2), nullable=False),
        # Numeric ohne Praezisionsgrenze: Der Kurs ist weder Geld noch Satz
        # (§ 8b) und wird hier nicht gerundet.
        sa.Column("kurs", sa.Numeric(), nullable=True),
        sa.Column("zahlbetrag_eur", sa.Numeric(12, 2), nullable=True),
        sa.Column("auftragsschluessel", sa.Text(), nullable=True),
        sa.Column("auftragsschluessel_offen", sa.Text(), nullable=True),
        sa.Column("uebergabe_beleg_id", sa.String(length=64), nullable=True),
        sa.Column("uebergabe_beleg_sha256", sa.String(length=64), nullable=True),
        sa.Column("bemerkung", sa.Text(), nullable=True),
        sa.Column("ausstellungsdatum", sa.Date(), nullable=True),
        sa.Column("pdf_filename", sa.String(length=255), nullable=True),
        sa.Column("datev_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archive_until", sa.Date(), nullable=True),
        sa.Column("storniert_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"]),
        sa.ForeignKeyConstraint(["storniert_id"], ["aufstellungen.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_aufstellungen_nummer"), "aufstellungen", ["nummer"], unique=True)
    op.create_index(op.f("ix_aufstellungen_status"), "aufstellungen", ["status"], unique=False)
    op.create_index(op.f("ix_aufstellungen_storniert_id"), "aufstellungen", ["storniert_id"], unique=False)
    op.create_index(
        "uq_aufstellungen_auftragsschluessel_offen",
        "aufstellungen",
        ["auftragsschluessel_offen"],
        unique=True,
        postgresql_where=sa.text("auftragsschluessel_offen IS NOT NULL"),
    )
    op.create_check_constraint(
        "ck_aufstellungen_status_wertevorrat",
        "aufstellungen",
        "status IN ('draft', 'issued', 'cancelled', 'discarded')",
    )
    op.create_check_constraint(
        "ck_aufstellungen_umrechnung_nur_bei_fremdwaehrung",
        "aufstellungen",
        "(waehrung = 'EUR') = (kurs IS NULL AND zahlbetrag_eur IS NULL)",
    )
    op.create_check_constraint(
        "ck_aufstellungen_summe",
        "aufstellungen",
        "brutto - quellensteuer = netto",
    )
    op.create_check_constraint(
        "ck_aufstellungen_auftragsschluessel_offen_wie_nachweis",
        "aufstellungen",
        "auftragsschluessel_offen IS NULL OR auftragsschluessel_offen = auftragsschluessel",
    )

    op.create_table("aufstellung_anlagen",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("aufstellung_id", sa.UUID(), nullable=False),
        sa.Column("quelle", sa.String(length=50), nullable=False),
        sa.Column("dateiname", sa.String(length=255), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("groesse", sa.Integer(), nullable=False),
        sa.Column("medientyp", sa.String(length=100), nullable=False),
        sa.ForeignKeyConstraint(["aufstellung_id"], ["aufstellungen.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "aufstellung_id", "quelle",
            name="uq_aufstellung_anlagen_aufstellung_quelle",
        ),
    )
    op.create_check_constraint(
        "ck_aufstellung_anlagen_quelle_wertevorrat",
        "aufstellung_anlagen",
        "quelle IN ('abrechnungsbericht', 'zahlungsbericht')",
    )
    op.create_check_constraint(
        "ck_aufstellung_anlagen_sha256_form",
        "aufstellung_anlagen",
        "sha256 ~ '^[0-9a-f]{64}$'",
    )

    # Nummernkreis: server_default versorgt die BESTANDS-Firmenzeile, die
    # ausserhalb des ORM entsteht; der Code liest die Werte danach ohne
    # Fallback — niemand muss an sie denken.
    op.add_column(
        "company",
        sa.Column("aufstellung_prefix", sa.String(length=20), server_default="AA-", nullable=False),
    )
    op.add_column(
        "company",
        sa.Column("aufstellung_counter", sa.Integer(), server_default="0", nullable=False),
    )

    # GoBD-Trigger gegen DELETE/TRUNCATE — dieselbe Quelle wie Migration 001
    # und die Testdatenbank (conftest). INSTALL_SQL ist idempotent (CREATE
    # OR REPLACE) und bringt die Trigger fuer alle Tabellen auf den
    # aktuellen Stand, die neuen eingeschlossen.
    op.execute(INSTALL_SQL)


def downgrade():
    # Tabellen fallen mit ihren Triggern; die gemeinsamen Trigger-Funktionen
    # bleiben stehen — sie gehoeren auch den Tabellen, die 001 angelegt hat.
    op.drop_table("aufstellung_anlagen")
    op.drop_table("aufstellungen")
    op.drop_column("company", "aufstellung_counter")
    op.drop_column("company", "aufstellung_prefix")
