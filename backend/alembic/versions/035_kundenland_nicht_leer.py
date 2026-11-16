"""Kundenland darf nicht leer sein

Revision ID: 035
Revises: 034
Create Date: 2026-11-17

Ein leeres Land landete als leeres CountryID-Element in der E-Rechnung (BR-57). Die
Formulare normalisieren seitdem auf "DE"; der CHECK sichert den Rest. NOT VALID: der
Bestand wird nicht geprüft, damit das Upgrade nie an einer alten Zeile scheitert; neue
und geänderte Zeilen gelten sofort. Bestand prüfen und die Bindung vollenden:
  SELECT count(*) FROM customers WHERE country = '';
  ALTER TABLE customers VALIDATE CONSTRAINT ck_customers_country_nicht_leer;
"""
from typing import Sequence, Union

from alembic import op

revision: str = "035"
down_revision: Union[str, None] = "034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE customers ADD CONSTRAINT ck_customers_country_nicht_leer "
               "CHECK (country <> '') NOT VALID")


def downgrade() -> None:
    op.execute("ALTER TABLE customers DROP CONSTRAINT ck_customers_country_nicht_leer")
