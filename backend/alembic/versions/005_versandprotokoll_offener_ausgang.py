"""invoice_send_log.success nullable: ein Versandversuch darf offenen Ausgang haben

Der Versandnachweis entstand bisher NACH dem SMTP-Versand. Schlug der Commit danach
fehl, war die Mail beim Kunden und beim Steuerbuero, und die Datenbank wusste nichts
davon; der naechste Klick schickte den Beleg ein zweites Mal (Bericht #10).

Seither wird die Protokollzeile geschrieben und committet, BEVOR SMTP angesprochen
wird. In der Zeit dazwischen ist der Ausgang offen, und dafuer braucht die Spalte
einen dritten Wert. NULL heisst „Versuch begonnen, Ergebnis unbekannt".

Warum nicht `false` als Zwischenstand: eine Zeile, die „fehlgeschlagen" sagt, obwohl
das niemand geprueft hat, ist genau die Auskunft, auf die hin jemand erneut sendet.
Der offene Ausgang ist unbequem und ehrlich, das falsche Kreuz ist bequem und falsch.

Nur Lockerung, kein Datenverlust: bestehende Zeilen haben alle true oder false und
behalten es. Das `downgrade` ist ehrlich nur moeglich, solange keine offene Zeile
existiert; Postgres bricht sonst von selbst ab, und das ist richtig so. Einen offenen
Ausgang hier still zu einem „fehlgeschlagen" zu erklaeren, waere schlimmer als der
Abbruch.

Revision ID: 005
Revises: 004
Create Date: 2026-08-23

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('invoice_send_log', 'success',
                    existing_type=sa.Boolean(),
                    nullable=True)


def downgrade() -> None:
    op.alter_column('invoice_send_log', 'success',
                    existing_type=sa.Boolean(),
                    nullable=False)
