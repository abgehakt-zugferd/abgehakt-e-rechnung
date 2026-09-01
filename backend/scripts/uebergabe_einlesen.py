#!/usr/bin/env python3
"""CLI: signierte Abrechnungsaufträge aus ZEMP_UEBERGABEN einlesen → Entwürfe.

Nur für Test/Integration — nicht gegen die Live-Installation ohne Wegwerf-DB.
Nutzt dieselbe Postgres wie die App (DATABASE_URL). Committet nach erfolgreichem Import.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from app.database import SessionLocal
from app.services.abrechnungsauftrag_import import ordner_einlesen


def main() -> int:
    wurzel = os.environ.get("ZEMP_UEBERGABEN")
    if not wurzel:
        print("ZEMP_UEBERGABEN ist nicht gesetzt", file=sys.stderr)
        return 2
    schluessel = Path(__file__).resolve().parents[1] / "schluessel"
    db = SessionLocal()
    try:
        entwuerfe = ordner_einlesen(db, Path(wurzel), schluessel_wurzel=schluessel)
        db.commit()
        print(f"{len(entwuerfe)} Entwurf(e) angelegt")
        for inv in entwuerfe:
            print(f"  {inv.invoice_number} → {inv.customer_id}")
        return 0
    except Exception as fehler:
        db.rollback()
        print(f"Fehler: {fehler}", file=sys.stderr)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
