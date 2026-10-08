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
from app.services.belegart import belegart
from app.services.invoice_guard import FINALIZED


class ErsatzNichtMoeglich(ValueError):
    """Die Rechnung darf (noch) nicht ersetzt werden. Der Code steht im Text,
    damit er in der HTTP-400-Antwort sichtbar ist."""

    def __init__(self, code: str, text: str):
        self.code = code
        super().__init__(f"{code}: {text}")


def _lade(db: Session, kennung: str | uuid.UUID) -> Invoice:
    try:
        original_id = kennung if isinstance(kennung, uuid.UUID) else uuid.UUID(str(kennung))
    except ValueError:
        original = None
    else:
        original = db.get(Invoice, original_id)
    if original is None:
        raise ErsatzNichtMoeglich(
            "ERSATZ_ORIGINAL_UNBEKANNT",
            f"Die zu ersetzende Rechnung {kennung!s} gibt es nicht.",
        )
    return original


def pruefe_ersetzbar(db: Session, kennung: str | uuid.UUID) -> Invoice:
    """Liefert die zu ersetzende Rechnung oder wirft ErsatzNichtMoeglich.

    `kennung` darf der rohe Formularwert sein; eine unbrauchbare Kennung ist
    eine Ablehnung wie jede andere, kein Serverfehler."""
    original = _lade(db, kennung)
    # Ersetzt wird nur eine gestellte, eigenstaendige Rechnung. Ein Folgebeleg
    # (381/384/389) hat seinen eigenen Korrekturweg; ein Entwurf ist noch frei
    # bearbeitbar und braucht keinen Ersatz.
    if original.status not in FINALIZED or belegart(original.invoice_type).braucht_original:
        raise ErsatzNichtMoeglich(
            "ERSATZ_ORIGINAL_KEINE_RECHNUNG",
            f"Beleg {original.invoice_number} ist keine gestellte Rechnung und "
            "kann deshalb nicht ersetzt werden.",
        )
    gutschrift = (
        db.query(Invoice.id)
        .filter(Invoice.original_invoice_id == original.id,
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
