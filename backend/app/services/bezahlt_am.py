"""Zahlungsdatum beim Markieren als bezahlt (Entscheidung 2026-09-30)."""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.models.invoice import Invoice


class BezahltAmFehler(ValueError):
    """Ungueltiges Zahlungsdatum: Klartext fuer die HTTP-Antwort."""


class BezahltTrotzGutschrift(ValueError):
    """Original mit aktiver Gutschrift darf nicht als bezahlt gelten (#15)."""


def parse_bezahlt_am(
    roh: str | None,
    *,
    heute: date,
    issue_date: date,
) -> date:
    """Liest ISO-Datum oder heute; lehnt Zukunft, Vor-Rechnung und Unlesbares ab."""
    if roh is None or not str(roh).strip():
        wert = heute
    else:
        try:
            wert = date.fromisoformat(str(roh).strip())
        except ValueError as exc:
            raise BezahltAmFehler(
                "Das Zahlungsdatum ist unlesbar. Bitte ein Datum im Format JJJJ-MM-TT angeben."
            ) from exc
    if wert > heute:
        raise BezahltAmFehler(
            "Das Zahlungsdatum darf nicht in der Zukunft liegen."
        )
    if wert < issue_date:
        raise BezahltAmFehler(
            "Das Zahlungsdatum darf nicht vor dem Rechnungsdatum liegen."
        )
    return wert


def aktive_gutschrift(db: Session, invoice: Invoice) -> Invoice | None:
    """Erste nicht-verworfene Gutschrift auf dieses Original, oder None.

    Bezahlt trotz Gutschrift (#15): ein Original mit Gutschrift darf nicht als
    bezahlt gelten. Auch der offene Entwurf sperrt, denn er ist die erklaerte
    Absicht zu korrigieren. Gesperrt wird nur der Weg nach paid; cancelled bleibt
    eine bewusste menschliche Entscheidung (paid ist Endzustand im Guard).
    """
    return (
        db.query(Invoice)
        .filter(
            Invoice.original_invoice_id == invoice.id,
            Invoice.status != "discarded",
        )
        .order_by(Invoice.invoice_number)
        .first()
    )


def _sperre_bei_gutschrift(db: Session, invoice: Invoice) -> None:
    """Wirft BezahltTrotzGutschrift, wenn eine aktive Gutschrift existiert."""
    # no_autoflush: Aufruf aus before_flush darf keinen verschachtelten Flush starten.
    with db.no_autoflush:
        gutschrift = aktive_gutschrift(db, invoice)
    if gutschrift is not None:
        raise BezahltTrotzGutschrift(
            f"Zu dieser Rechnung existiert die Gutschrift "
            f"{gutschrift.invoice_number}. Ein stornierter Beleg kann nicht als "
            "bezahlt geführt werden. Setze ihn auf „storniert“, oder verwirf "
            "die Gutschrift, falls sie versehentlich entstanden ist."
        )


def absichern_bezahlt(db: Session, invoice: Invoice, *, heute: date) -> None:
    """Zweite Schicht (Guard): Gutschrift und Datumsfenster bei Wechsel nach paid.

    Erwartet bezahlt_am bereits gesetzt. Nutzt dieselbe Abfrage und dieselbe
    Datumsregel wie vorbereiten_bezahlt / parse_bezahlt_am (#174).
    """
    _sperre_bei_gutschrift(db, invoice)
    if invoice.bezahlt_am is None:
        raise BezahltAmFehler(
            "Bezahlt ohne Zahlungsdatum (bezahlt_am) ist nicht erlaubt."
        )
    parse_bezahlt_am(
        invoice.bezahlt_am.isoformat(),
        heute=heute,
        issue_date=invoice.issue_date,
    )


def vorbereiten_bezahlt(
    db: Session,
    invoice: Invoice,
    roh_bezahlt_am: str | None,
    *,
    heute: date,
) -> None:
    """Prueft Gutschrift-Sperre und setzt bezahlt_am am Beleg."""
    _sperre_bei_gutschrift(db, invoice)
    invoice.bezahlt_am = parse_bezahlt_am(
        roh_bezahlt_am, heute=heute, issue_date=invoice.issue_date,
    )
