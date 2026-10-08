"""Ersatzrechnung zu einer stornierten Rechnung (docs/specs/ersatzrechnung.md).

Eine Ersatzrechnung ist eine gewoehnliche Rechnung (380/386), die per BT-25 auf
genau eine Rechnung verweist, zu der es eine Gutschrift gibt. Dieses Modul
beantwortet die eine Frage, ob eine Rechnung ersetzt werden darf. Router und
Validator fragen hier, statt die Regeln selbst zu kennen.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models.invoice import Invoice


class ErsatzNichtMoeglich(ValueError):
    """Die Rechnung darf (noch) nicht ersetzt werden. Der Code steht im Text,
    damit er in der HTTP-400-Antwort sichtbar ist."""

    def __init__(self, code: str, text: str):
        self.code = code
        super().__init__(f"{code}: {text}")


def pruefe_ersetzbar(db: Session, original_id: uuid.UUID) -> Invoice:
    """Liefert die zu ersetzende Rechnung oder wirft ErsatzNichtMoeglich."""
    original = db.get(Invoice, original_id)
    gutschrift = (
        db.query(Invoice.id)
        .filter(Invoice.original_invoice_id == original_id,
                Invoice.invoice_type == "credit_note",
                Invoice.status != "discarded")
        .first()
    )
    if gutschrift is None:
        raise ErsatzNichtMoeglich(
            "ERSATZ_OHNE_GUTSCHRIFT",
            f"Zu Rechnung {original.invoice_number} gibt es keine Gutschrift. Eine "
            "Ersatzrechnung entsteht erst, wenn die falsche Rechnung storniert ist; "
            "sonst stuenden zwei Rechnungen ueber dieselbe Leistung in den Buechern.",
        )
    return original
