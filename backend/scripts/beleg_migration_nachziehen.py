"""Versand- und Zahlungsstatus fuer aus altem Abgehakt importierte Belege nachziehen.

Im alten System waren die Belege laengst versendet und bezahlt; der XML-Import
kennt nur issued. Dieses Skript setzt datev_sent_at, optional bezahlt_am
(historischer Zahlungskalendertag) und ein Versandprotokoll, ohne erneuten
Mailversand. updated_at bleibt der echte Aenderungszeitpunkt des Nachziehens.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.invoice import Invoice, InvoiceSendLog
from app.services.bezahlt_am import (
    BezahltAmFehler,
    BezahltTrotzGutschrift,
    vorbereiten_bezahlt,
)
from app.zeit import heute

HINWEIS_MIGRATION = "Historischer Versand (vorheriges Abgehakt, kein erneuter Versand)."


def _utc_mittag(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc)


def _bezahlt_zeitpunkt(
    inv: Invoice,
    bezahlt_am: datetime | None,
    *,
    nummer: str,
) -> datetime:
    """Liefert den historischen Bezahlt-Zeitpunkt oder bricht klar ab."""
    if bezahlt_am is not None:
        return bezahlt_am
    if inv.due_date is None:
        raise ValueError(
            f"{nummer}: kein Faelligkeitsdatum und kein bezahlt_am — Abbruch."
        )
    return _utc_mittag(inv.due_date)


def _als_bezahlt_setzen(db: Session, inv: Invoice, paid: datetime, *, nummer: str) -> None:
    """Setzt paid ueber vorbereiten_bezahlt (Guard- und Datumsregel)."""
    roh = paid.astimezone(ZoneInfo("Europe/Berlin")).date().isoformat()
    try:
        vorbereiten_bezahlt(db, inv, roh, heute=heute())
    except (BezahltTrotzGutschrift, BezahltAmFehler) as exc:
        raise ValueError(f"{nummer}: {exc}") from exc
    inv.status = "paid"
    print(f"{nummer}: Status → bezahlt (bezahlt_am {roh})")


def _versand_setzen(inv: Invoice, sent: datetime, *, nummer: str) -> None:
    # Historischer Versand: Kunde und Buchhaltung zusammen (Migration 029).
    if inv.datev_sent_at is None:
        inv.datev_sent_at = sent
        inv.kunde_zugestellt_am = sent
        print(f"{nummer}: Versand {sent.strftime('%d.%m.%Y')}")
    else:
        print(f"{nummer}: Versand bereits {inv.datev_sent_at.strftime('%d.%m.%Y')}")


def _protokoll_anlegen(db: Session, inv: Invoice, sent: datetime, *, nummer: str) -> None:
    if db.query(InvoiceSendLog).filter(InvoiceSendLog.invoice_id == inv.id).count():
        return
    to_email = inv.customer.email if inv.customer and inv.customer.email else "unbekannt@import"
    db.add(InvoiceSendLog(
        invoice_id=inv.id,
        ziel="kunde_und_buchhaltung",
        sent_at=sent,
        to_email=to_email,
        datev_bcc=True,
        success=True,
        error=HINWEIS_MIGRATION,
    ))
    print(f"{nummer}: Versandprotokoll angelegt")


def _eine_nummer(
    db: Session,
    num: str,
    *,
    versendet_am: datetime | None,
    bezahlt_am: datetime | None,
    als_bezahlt: bool,
) -> None:
    inv = db.query(Invoice).filter(Invoice.invoice_number == num).first()
    if not inv:
        print(f"FEHLER: {num} nicht gefunden")
        return
    sent = versendet_am or _utc_mittag(inv.issue_date)
    paid = _bezahlt_zeitpunkt(inv, bezahlt_am, nummer=num) if als_bezahlt else None
    _versand_setzen(inv, sent, nummer=num)
    if als_bezahlt and inv.status != "paid":
        _als_bezahlt_setzen(db, inv, paid, nummer=num)
    _protokoll_anlegen(db, inv, sent, nummer=num)
    db.commit()
    print(f"ok: {num}")


def nachziehen(
    nummern: list[str],
    *,
    db: Session | None = None,
    versendet_am: datetime | None = None,
    bezahlt_am: datetime | None = None,
    als_bezahlt: bool = True,
) -> None:
    own_session = db is None
    if db is None:
        db = SessionLocal()
    try:
        for num in nummern:
            _eine_nummer(
                db, num,
                versendet_am=versendet_am,
                bezahlt_am=bezahlt_am,
                als_bezahlt=als_bezahlt,
            )
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    nums = sys.argv[1:] or ["Z-2026-002", "Z-2026-004"]
    nachziehen(nums)
