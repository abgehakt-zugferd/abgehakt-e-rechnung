#!/usr/bin/env python3
"""CLI: erfundene Testdaten fuer eine Test-VM anlegen.

Legt an: eine erfundene Firma (nur wenn keine eingerichtete existiert), zwei
erfundene Kunden (einen deutschen, einen aus Oesterreich mit Platzhalter-USt-IdNr.)
und zwei Rechnungsentwuerfe mit Positionen. Mit `--finalisieren` werden die
Entwuerfe ueber den normalen Dienstweg gestellt (PDF/A-3 mit eingebetteter XML,
Mustang-Pruefung, Ablage unter storage/), nicht per SQL.

Schutz: Enthaelt die Datenbank schon Kunden oder Rechnungen, bricht das Skript ab,
ohne etwas zu schreiben. `--erzwingen` hebt den Schutz auf.

Aufruf im Container:
    docker compose exec app python -m scripts.seed_testdaten [--finalisieren] [--erzwingen]

Alle Werte sind offensichtliche Platzhalter. Nichts davon ist eine echte Firma,
Steuernummer oder USt-IdNr.; das Skript gehoert nicht in eine Live-Installation.
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from sqlalchemy.orm import Session

# Zeichenketten zerlegt wie in tests/probe_daten.py: die Datenwache soll sie als
# erfundene Folgen erkennen, und kein Suchlauf findet sie als echte Nummer.
UST_FIRMA = "DE" + "123456789"
STEUERNUMMER_FIRMA = "12" + "/" + "345" + "/" + "67890"
UST_KUNDE_AT = "ATU" + "12345678"
REGISTERNUMMER = "HRB" + " " + "00000"

_CENT = Decimal("0.01")


def _firma_felder() -> dict:
    return dict(
        name="Beispiel Musterfirma GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", country="DE",
        tax_number=STEUERNUMMER_FIRMA, vat_id=UST_FIRMA,
        email="rechnung@example.invalid", rechtsform="gmbh",
        registergericht="Amtsgericht Musterstadt", registernummer=REGISTERNUMMER,
        vertretung="Erika Mustermann",
    )


def _bestand_vorhanden(db: Session) -> bool:
    from app.models.customer import Customer
    from app.models.invoice import Invoice
    return db.query(Customer).count() > 0 or db.query(Invoice).count() > 0


def _firma_sicherstellen(db: Session) -> None:
    """Eine eingerichtete Firma bleibt unberuehrt; sonst wird sie angelegt/gefuellt."""
    from app.models.company import Company
    from app.services.ersteinrichtung import einrichtung_abschliessen, ist_eingerichtet
    firma = db.query(Company).filter(Company.id == 1).first()
    if ist_eingerichtet(firma):
        return
    if firma is None:
        firma = Company(id=1, **_firma_felder())
        db.add(firma)
    else:
        for feld, wert in _firma_felder().items():
            setattr(firma, feld, wert)
    einrichtung_abschliessen(firma)
    db.flush()


def _kunde_anlegen(db: Session, **felder):
    from app.models.customer import Customer
    from app.services.customer_number import next_customer_number
    kunde = Customer(customer_number=next_customer_number(db), **felder)
    db.add(kunde)
    db.flush()
    return kunde


def _kunden_anlegen(db: Session) -> tuple:
    inland = _kunde_anlegen(
        db, name="Muster Kunde Inland GmbH", address_line1="Beispielweg 2",
        zip_code="10115", city="Berlin", country="DE", email="inland@example.invalid")
    ausland = _kunde_anlegen(
        db, name="Muster Kunde Österreich GmbH", address_line1="Beispielgasse 3",
        zip_code="1010", city="Wien", country="AT", vat_id=UST_KUNDE_AT,
        email="ausland@example.invalid")
    return inland, ausland


def _position(nummer: int, text: str, einheit: str, menge: str, preis: str, satz: str):
    from app.models.invoice_nebenmodelle import InvoiceItem
    menge_d, preis_d, satz_d = Decimal(menge), Decimal(preis), Decimal(satz)
    netto = (menge_d * preis_d).quantize(_CENT, rounding=ROUND_HALF_UP)
    steuer = (netto * satz_d / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
    return InvoiceItem(
        position=nummer, description=text, unit=einheit, quantity=menge_d,
        unit_price=preis_d, tax_rate=satz_d, net_amount=netto, tax_amount=steuer,
        gross_amount=netto + steuer)


def _entwurf_anlegen(db: Session, kunde, kategorie: str, positionen: list):
    from app.models.invoice import Invoice
    from app.services.archive_frist import berechne_archive_until
    from app.services.belegsummen import belegsummen
    from app.services.invoice_number import generate_next_invoice_number
    from app.zeit import heute
    tag = heute()
    summen = belegsummen(positionen, None)
    rechnung = Invoice(
        invoice_number=generate_next_invoice_number(db, issue_date=tag),
        customer_id=kunde.id, issue_date=tag, delivery_date=tag,
        due_date=tag + timedelta(days=14), currency="EUR", status="draft",
        tax_category=kategorie, payment_terms="Zahlbar innerhalb von 14 Tagen ohne Abzug.",
        net_total=summen.steuerbasis, tax_total=summen.steuer, gross_total=summen.brutto,
        archive_until=berechne_archive_until(tag))
    rechnung.items = positionen
    db.add(rechnung)
    db.flush()
    return rechnung


def _entwuerfe_anlegen(db: Session, inland, ausland) -> list:
    return [
        _entwurf_anlegen(db, inland, "S", [
            _position(1, "Beratung (Beispiel)", "Stunde", "2", "100.00", "19"),
            _position(2, "Einrichtungspauschale (Beispiel)", "Stück", "1", "50.00", "19"),
        ]),
        _entwurf_anlegen(db, ausland, "AE", [
            _position(1, "Schulung (Beispiel)", "Tag", "1", "800.00", "0"),
        ]),
    ]


def _finalisieren(db: Session, rechnungen: list) -> None:
    """Normaler Dienstweg; eine Mustang-Warnung wird wie in der Oberflaeche bestaetigt."""
    from app.services.rechnung.fehler import FinalisierungWarnung
    from app.services.rechnung.finalisieren import ausfuehren
    for rechnung in rechnungen:
        nummer, kennung = rechnung.invoice_number, rechnung.id
        try:
            ausfuehren(db, kennung)
        except FinalisierungWarnung as warnung:
            ausfuehren(db, kennung, warnung.schluessel, warnung.xml_sha256)
        print(f"Finalisiert: {nummer}")


def _dienstweg_registrieren() -> None:
    """Guards und Audit wie beim Start der Anwendung (idempotent, Guards zuerst)."""
    from app.services.aufstellung_guard import register_aufstellung_guard
    from app.services.audit import register_audit_listeners
    from app.services.customer_guard import register_customer_guard
    from app.services.invoice_guard import register_invoice_guard
    register_invoice_guard()
    register_aufstellung_guard()
    register_customer_guard()
    register_audit_listeners()


def _anlegen(db: Session, finalisieren: bool) -> None:
    _firma_sicherstellen(db)
    inland, ausland = _kunden_anlegen(db)
    rechnungen = _entwuerfe_anlegen(db, inland, ausland)
    db.commit()
    print(f"Angelegt: 2 Kunden, {len(rechnungen)} Rechnungsentwürfe.")
    if finalisieren:
        _finalisieren(db, rechnungen)


def main(argv: Optional[list[str]] = None, *, db: Optional[Session] = None) -> int:
    parser = argparse.ArgumentParser(description="Erfundene Testdaten anlegen (Test-VM).")
    parser.add_argument("--finalisieren", action="store_true",
                        help="Entwürfe über den normalen Dienstweg als E-Rechnung stellen")
    parser.add_argument("--erzwingen", action="store_true",
                        help="auch anlegen, wenn die Datenbank schon Kunden oder Rechnungen enthält")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    _dienstweg_registrieren()
    eigene = db is None
    if eigene:
        from app.database import SessionLocal
        db = SessionLocal()
    try:
        if _bestand_vorhanden(db) and not args.erzwingen:
            print("Abbruch: Die Datenbank enthält schon Kunden oder Rechnungen. "
                  "Nichts geschrieben. Mit --erzwingen trotzdem anlegen.", file=sys.stderr)
            return 1
        _anlegen(db, args.finalisieren)
        return 0
    finally:
        if eigene:
            db.close()


if __name__ == "__main__":
    sys.exit(main())
