"""Belegsprache und englische Zahlungsbedingungen-Vorgabe

invoices.document_language: Zweibuchstabencode, Default und Bestand explizit `de`
(der heutige Generator ist deutsch; keine Ableitung aus Land oder Freitext).
company.payment_terms_default_en: leer fuer Bestand, keine erfundenen Vertragstexte.
Erzeugt keine PDFs/XML neu und aendert keine Archivdateien.

Revision ID: 015
Revises: 014
Create Date: 2026-09-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "invoices",
        sa.Column(
            "document_language",
            sa.String(length=2),
            nullable=False,
            server_default="de",
        ),
    )
    # Explizit fuer Bestand: Herkunftsbefund des Generators, nicht Land/Freitext.
    op.execute(sa.text("UPDATE invoices SET document_language = 'de'"))

    op.add_column(
        "company",
        sa.Column("payment_terms_default_en", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("company", "payment_terms_default_en")
    op.drop_column("invoices", "document_language")
