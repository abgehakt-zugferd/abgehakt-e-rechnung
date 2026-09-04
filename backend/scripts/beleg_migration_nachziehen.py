"""Versand- und Zahlungsstatus fuer aus altem Abgehakt importierte Belege nachziehen.

Im alten System waren die Belege laengst versendet und bezahlt; der XML-Import
kennt nur issued. Dieses Skript setzt datev_sent_at, optional den Bezahlt-
Zeitpunkt (updated_at) und ein Versandprotokoll — ohne erneuten Mailversand.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.invoice import Invoice, InvoiceSendLog

HINWEIS_MIGRATION = "Historischer Versand (vorheriges Abgehakt, kein erneuter Versand)."


def _utc_mittag(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=timezone.utc)


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
            inv = db.query(Invoice).filter(Invoice.invoice_number == num).first()
            if not inv:
                print(f"FEHLER: {num} nicht gefunden")
                continue

            sent = versendet_am or _utc_mittag(inv.issue_date)
            paid = bezahlt_am or _utc_mittag(inv.due_date)

            if inv.datev_sent_at is None:
                inv.datev_sent_at = sent
                print(f"{num}: Versand {sent.strftime('%d.%m.%Y')}")
            else:
                print(f"{num}: Versand bereits {inv.datev_sent_at.strftime('%d.%m.%Y')}")

            if als_bezahlt and inv.status != "paid":
                inv.status = "paid"
                print(f"{num}: Status → bezahlt")

            if not db.query(InvoiceSendLog).filter(InvoiceSendLog.invoice_id == inv.id).count():
                to_email = inv.customer.email if inv.customer and inv.customer.email else "unbekannt@import"
                db.add(InvoiceSendLog(
                    invoice_id=inv.id,
                    sent_at=sent,
                    to_email=to_email,
                    datev_bcc=True,
                    success=True,
                    error=HINWEIS_MIGRATION,
                ))
                print(f"{num}: Versandprotokoll angelegt")

            db.flush()
            # updated_at hat onupdate=now() — nur per SQL zurueckdatieren.
            if als_bezahlt and inv.status == "paid":
                db.execute(
                    text("UPDATE invoices SET updated_at = :paid WHERE id = :id"),
                    {"paid": paid, "id": inv.id},
                )
                print(f"{num}: Bezahlt-Zeitpunkt {paid.strftime('%d.%m.%Y')}")

            db.commit()
            print(f"ok: {num}")
    finally:
        if own_session:
            db.close()


if __name__ == "__main__":
    nums = sys.argv[1:] or ["Z-2026-002", "Z-2026-004"]
    nachziehen(nums)
