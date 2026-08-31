"""Kopie der Rechnungsmail: mehrere Adressen, je Kunde hinterlegbar

Bisher gab es genau ein Feld fuer die Kopie, und es galt global fuer jeden Kunden
(`app_config.invoice_cc_email`). Sind beim Kunden zwei Personen zustaendig, half das
nicht: wer die zweite Adresse in die Voreinstellung schrieb, setzte sie kuenftig bei
allen anderen Kunden mit in Kopie (Bericht #58).

`customers.cc_emails` haelt die Liste dort, wo sie hingehoert. Die Voreinstellung
bleibt als Rueckfall bestehen; Vorrang hat der Kunde.

Die drei Spalten wachsen auf 500 Zeichen, weil sie jetzt eine Liste halten und nicht
mehr eine Adresse. `invoice_send_log.cc_email` ist dabei die wichtigste: dort steht,
wer den Beleg tatsaechlich bekommen hat. Waere sie zu schmal, braeche der Versand
erst beim Schreiben des Nachweises ab, also nachdem die Mail draussen ist.

Nur Erweiterung, kein Datenverlust: bestehende Werte passen unveraendert in die
groesseren Spalten. Das `downgrade` verengt wieder auf 255; laengere Werte laesst
Postgres dann von selbst nicht zu, und das ist richtig so.

Revision ID: 006
Revises: 005
Create Date: 2026-08-31

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '006'
down_revision: Union[str, None] = '005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('customers', sa.Column('cc_emails', sa.String(length=500), nullable=True))
    op.alter_column('app_config', 'invoice_cc_email',
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=500),
                    existing_nullable=True)
    op.alter_column('invoice_send_log', 'cc_email',
                    existing_type=sa.String(length=255),
                    type_=sa.String(length=500),
                    existing_nullable=True)


def downgrade() -> None:
    op.alter_column('invoice_send_log', 'cc_email',
                    existing_type=sa.String(length=500),
                    type_=sa.String(length=255),
                    existing_nullable=True)
    op.alter_column('app_config', 'invoice_cc_email',
                    existing_type=sa.String(length=500),
                    type_=sa.String(length=255),
                    existing_nullable=True)
    op.drop_column('customers', 'cc_emails')
