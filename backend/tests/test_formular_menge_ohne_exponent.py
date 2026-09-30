"""Das Bearbeitungsformular zeigt eine Menge von 60 als 60, nicht als 6E+1.

`Decimal("60.0000").normalize()` ist `Decimal("6E+1")`; `str()` davon landete
im Zahlenfeld des Formulars. Betroffen war jede durch zehn teilbare Menge, auf
allen drei Wegen ins Formular: neu, bearbeiten, aus Vorlage. Gefunden am
2026-09-30 an Z-2026-010 (60 Stunden). Das PDF kannte die Falle schon
(`pdf_generator.py`), das Formular nicht.
"""
import json
import re
from decimal import Decimal

import pytest

from app.models.invoice import InvoiceItem
from tests.test_invoice_edit import _client, _customer, _invoice


def _positionen(html: str) -> list[dict]:
    treffer = re.search(r"(\[\{.*?\}\])", html, re.S)
    assert treffer, "Positionsliste nicht im Formular gefunden"
    return json.loads(treffer.group(1).replace("<\\/", "</"))


@pytest.mark.parametrize("menge,erwartet", [
    ("60.0000", "60"),
    ("120.0000", "120"),
    ("61.5000", "61.5"),
    ("0.2500", "0.25"),
    ("1.0000", "1"),
])
def test_menge_kommt_ohne_exponent_ins_formular(pg_session, menge, erwartet):
    inv = _invoice(pg_session, _customer(pg_session))
    item = pg_session.query(InvoiceItem).filter_by(invoice_id=inv.id).one()
    item.quantity = Decimal(menge)
    pg_session.commit()

    r = _client(pg_session).get(f"/invoices/{inv.id}/bearbeiten")

    assert r.status_code == 200
    assert _positionen(r.text)[0]["quantity"] == erwartet
