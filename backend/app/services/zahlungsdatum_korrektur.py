"""Zahlungsdatum eines bezahlten Belegs korrigieren, mit Grund (#278).

GoBD verlangt nicht, dass eine Angabe nie geaendert wird, sondern dass der
urspruengliche Inhalt feststellbar bleibt (Paragraf 146 Abs. 4 AO). Das
Aenderungsprotokoll haelt alten und neuen Wert, den Grund und den Zeitpunkt.
Status, PDF, XML und Archiv bleiben unberuehrt.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.invoice import Invoice
from app.services.bezahlt_am import BezahltAmFehler, parse_bezahlt_am
from app.services.zahlungsdatum_durchlass import durchlass


class ZahlungsdatumKorrekturFehler(ValueError):
    """Korrektur nicht moeglich: Klartext fuer die HTTP-Antwort."""


def korrigieren(
    db: Session, invoice: Invoice, roh_datum: str | None, grund: str | None,
    *, heute: date,
) -> None:
    """Setzt das neue Zahlungsdatum; der Aufrufer committet."""
    if invoice.status != "paid" or invoice.bezahlt_am is None:
        raise ZahlungsdatumKorrekturFehler(
            "Das Zahlungsdatum lässt sich nur an einem bezahlten Beleg korrigieren."
        )
    grund = (grund or "").strip()
    if not grund:
        raise ZahlungsdatumKorrekturFehler(
            "Bitte den Grund der Korrektur angeben."
        )
    if roh_datum is None or not roh_datum.strip():
        raise ZahlungsdatumKorrekturFehler("Bitte das neue Zahlungsdatum angeben.")
    try:
        neu = parse_bezahlt_am(roh_datum, heute=heute, invoice=invoice)
    except BezahltAmFehler as exc:
        raise ZahlungsdatumKorrekturFehler(str(exc)) from exc
    if neu == invoice.bezahlt_am:
        raise ZahlungsdatumKorrekturFehler(
            "Das neue Zahlungsdatum entspricht dem bisherigen."
        )
    with durchlass(db, invoice.id, grund):
        invoice.bezahlt_am = neu
        db.flush()
