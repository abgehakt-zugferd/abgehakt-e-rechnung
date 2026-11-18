"""Firmenland darf nicht leer sein

Revision ID: 036
Revises: 035
Create Date: 2026-11-18

Wie 035 für Kunden: Ein leeres Land der eigenen Firma landete als leeres CountryID-Element
in der Verkäuferanschrift. Die Formulare normalisieren auf "DE"; der CHECK sichert den
Rest. NOT VALID: fremde Installationen können Altzeilen haben, das Upgrade darf daran
nicht scheitern; neue und geänderte Zeilen gelten sofort. Bestand prüfen und die Bindung
vollenden:
  SELECT count(*) FROM company WHERE country = '';
  ALTER TABLE company VALIDATE CONSTRAINT ck_company_country_nicht_leer;
"""
from typing import Sequence, Union

from alembic import op

revision: str = "036"
down_revision: Union[str, None] = "035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE company ADD CONSTRAINT ck_company_country_nicht_leer "
               "CHECK (country <> '') NOT VALID")


def downgrade() -> None:
    op.execute("ALTER TABLE company DROP CONSTRAINT ck_company_country_nicht_leer")
