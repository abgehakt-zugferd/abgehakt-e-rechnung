"""Partielle Eindeutigkeit: eine aktive Gutschrift pro Original (#90)

Zwei gleichzeitige Stornoanfragen lesen beide "keine vorhanden" und legen
beide an. Die Vorabpruefung in der Anwendung nimmt keine Sperre; die Zusage
gehoert deshalb in die Datenbank, analog zu den GoBD-Ausloesern neben den
ORM-Waechtern.

Revision ID: 013
Revises: 012
Create Date: 2026-09-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_invoices_eine_aktive_gutschrift_pro_original"
WHERE = "status <> 'discarded' AND original_invoice_id IS NOT NULL"


def upgrade() -> None:
    # Harter Abbruch mit Bericht: stille Korrektur an Bestandsdaten waere eine
    # Belegfälschung. Wer doppelt storniert hat, muss die Lage zuerst von Hand
    # klaeren (eine der Gutschriften verwerfen, falls noch Entwurf, oder den
    # fachlichen Weg ausserhalb dieser Migration).
    conn = op.get_bind()
    doppelte = conn.execute(
        sa.text(
            """
            SELECT original_invoice_id::text, COUNT(*) AS n,
                   string_agg(invoice_number, ', ' ORDER BY invoice_number) AS nummern
            FROM invoices
            WHERE original_invoice_id IS NOT NULL
              AND status <> 'discarded'
            GROUP BY original_invoice_id
            HAVING COUNT(*) > 1
            ORDER BY original_invoice_id
            """
        )
    ).fetchall()
    if doppelte:
        zeilen = "; ".join(
            f"{row.original_invoice_id} ({row.n}x: {row.nummern})" for row in doppelte
        )
        raise RuntimeError(
            "Migration 013 (#90) bricht ab: zum selben Original gibt es mehr als "
            "eine nicht verworfene Gutschrift. Nichts wird automatisch geloescht "
            "oder umgeschrieben. Klaere den Bestand von Hand, dann erneut "
            f"upgrade. Betroffen: {zeilen}"
        )

    op.create_index(
        INDEX_NAME,
        "invoices",
        ["original_invoice_id"],
        unique=True,
        postgresql_where=sa.text(WHERE),
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="invoices")
