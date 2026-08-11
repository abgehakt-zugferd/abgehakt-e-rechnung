"""invoices.customer_id nullable: ein Entwurf darf noch keinen Kunden haben

Vorher war die Spalte NOT NULL, und damit war der Empfaenger ein Pflichtfeld des
Formulars. Wer eine Rechnung fuer einen noch nicht angelegten Kunden vorbereitete,
tippte Positionen und Termine, klickte auf Speichern und bekam das Formular mit einer
Pflichtfeldmeldung zurueck. Ein Entwurf, der Pflichtfelder hat, ist kein Entwurf.

Die Pflicht verschwindet damit nicht, sie steht nur an der richtigen Stelle. Fuer die
fertige Rechnung verlangt § 14 Abs. 4 Nr. 1 UStG den Empfaenger; durchgesetzt wird das
von `validator.validate_invoice` (`BUYER_MISSING`, harter Fehler) vor dem
fail-closed-Finalisieren. Ein Entwurf ohne Kunden laesst sich speichern und niemals
finalisieren.

Nur Lockerung, kein Datenverlust: bestehende Zeilen haben alle einen Kunden und
behalten ihn. Das `downgrade` ist deshalb ehrlich nur moeglich, solange keine
kundenlose Zeile existiert; Postgres bricht sonst von selbst ab, und das ist richtig
so. Es waere schlimmer, hier still einen Ersatzkunden zu erfinden.

Revision ID: 004
Revises: 003
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects.postgresql import UUID


revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('invoices', 'customer_id',
                    existing_type=UUID(as_uuid=True),
                    nullable=True)


def downgrade() -> None:
    op.alter_column('invoices', 'customer_id',
                    existing_type=UUID(as_uuid=True),
                    nullable=False)
