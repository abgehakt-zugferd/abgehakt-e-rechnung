"""Vorschlag für Kundennummern im Schema JJJJMM + laufende Nr. (pro Monat).

Beispiel: 20260703 = Jahr 2026, Monat 07, dritte Nummer dieses Monats.
Der Vorschlag ist überschreibbar — bestehende (auch abweichend formatierte)
Kundennummern lassen sich manuell eintragen.
"""
import re
from datetime import date

from sqlalchemy.orm import Session

from app.models.customer import Customer


def next_customer_number(db: Session, today: date | None = None) -> str:
    today = today or date.today()
    prefix = today.strftime("%Y%m")
    pattern = re.compile(rf"^{prefix}(\d+)$")

    rows = db.query(Customer.customer_number).filter(
        Customer.customer_number.like(f"{prefix}%")
    ).all()

    max_seq = 0
    for (number,) in rows:
        m = pattern.match(number or "")
        if m:
            max_seq = max(max_seq, int(m.group(1)))

    return f"{prefix}{str(max_seq + 1).zfill(2)}"
