"""Einmaliger Import: finalisierte Belege aus storage/xml + storage/pdfs in die DB.

Liest die XML (rechtlich maßgebliche Quelle), legt Kunde falls nötig nicht an —
nur vorhandene Kunden per USt-IdNr. — und erzeugt issued-Rechnungen mit Positionen.
"""
from __future__ import annotations

import sys
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from xml.etree import ElementTree as ET

from app.config import get_settings
from app.database import SessionLocal
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.archive_frist import berechne_archive_until

RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
UDT = "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100"
RSM = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"

UNIT_AUS_CODE = {
    "C62": "Stück",
    "HUR": "Stunde",
    "DAY": "Tag",
    "MON": "Monat",
    "KMT": "Kilometer",
    "MTR": "Meter",
    "KGM": "kg",
    "LTR": "Liter",
    "LS": "Pauschal",
}


def _q(ns: str, local: str) -> str:
    return f"{{{ns}}}{local}"


def _text(el: ET.Element | None) -> str:
    return (el.text or "").strip() if el is not None else ""


def _date102(raw: str | None) -> date | None:
    if not raw or len(raw) != 8:
        return None
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def _find_buyer_vat(root: ET.Element) -> str | None:
    buyer = root.find(f".//{_q(RAM, 'BuyerTradeParty')}")
    if buyer is None:
        return None
    for reg in buyer.iter(_q(RAM, "SpecifiedTaxRegistration")):
        id_el = reg.find(_q(RAM, "ID"))
        if id_el is not None and id_el.get("schemeID") == "VA":
            return _text(id_el).replace(" ", "").upper()
    return None


def _parse(xml_path: Path) -> dict:
    root = ET.parse(xml_path).getroot()
    doc = root.find(f".//{_q(RSM, 'ExchangedDocument')}")
    if doc is None:
        raise ValueError(f"{xml_path}: ExchangedDocument fehlt")

    number = _text(doc.find(_q(RAM, "ID")))
    issue_raw = _text(doc.find(f".//{_q(RAM, 'IssueDateTime')}/{_q(UDT, 'DateTimeString')}"))
    issue_date = _date102(issue_raw)
    if not issue_date:
        raise ValueError(f"{xml_path}: Rechnungsdatum fehlt")

    notes_el = doc.find(_q(RAM, "IncludedNote"))
    notes = _text(notes_el.find(_q(RAM, "Content"))) if notes_el is not None else None
    if notes in ("None", ""):
        notes = None

    delivery_raw = _text(
        root.find(
            f".//{_q(RAM, 'ActualDeliverySupplyChainEvent')}"
            f"/{_q(RAM, 'OccurrenceDateTime')}/{_q(UDT, 'DateTimeString')}"
        )
    )
    delivery_date = _date102(delivery_raw)

    settlement = root.find(f".//{_q(RAM, 'ApplicableHeaderTradeSettlement')}")
    if settlement is None:
        raise ValueError(f"{xml_path}: Settlement fehlt")

    due_raw = _text(
        settlement.find(
            f".//{_q(RAM, 'SpecifiedTradePaymentTerms')}"
            f"/{_q(RAM, 'DueDateDateTime')}/{_q(UDT, 'DateTimeString')}"
        )
    )
    due_date = _date102(due_raw)
    if not due_date:
        raise ValueError(f"{xml_path}: Fälligkeitsdatum fehlt")

    payment_terms = _text(
        settlement.find(
            f".//{_q(RAM, 'SpecifiedTradePaymentTerms')}/{_q(RAM, 'Description')}"
        )
    ) or None

    summation = settlement.find(_q(RAM, "SpecifiedTradeSettlementHeaderMonetarySummation"))
    if summation is None:
        raise ValueError(f"{xml_path}: Summation fehlt")

    net = Decimal(_text(summation.find(_q(RAM, "LineTotalAmount"))))
    tax = Decimal(_text(summation.find(_q(RAM, "TaxTotalAmount"))))
    gross = Decimal(_text(summation.find(_q(RAM, "GrandTotalAmount"))))

    tax_header = settlement.find(_q(RAM, "ApplicableTradeTax"))
    category = _text(tax_header.find(_q(RAM, "CategoryCode"))) if tax_header is not None else "S"
    if not category:
        category = "S"

    items = []
    for line in root.findall(f".//{_q(RAM, 'IncludedSupplyChainTradeLineItem')}"):
        pos = int(_text(line.find(f".//{_q(RAM, 'LineID')}")) or len(items) + 1)
        desc = _text(line.find(f".//{_q(RAM, 'SpecifiedTradeProduct')}/{_q(RAM, 'Name')}"))
        qty_el = line.find(f".//{_q(RAM, 'BilledQuantity')}")
        unit_code = qty_el.get("unitCode", "C62") if qty_el is not None else "C62"
        unit = UNIT_AUS_CODE.get(unit_code, "Stück")
        quantity = Decimal(_text(qty_el) or "1")
        net_line = Decimal(_text(
            line.find(
                f".//{_q(RAM, 'SpecifiedTradeSettlementLineMonetarySummation')}"
                f"/{_q(RAM, 'LineTotalAmount')}"
            )
        ))
        rate = Decimal(_text(line.find(f".//{_q(RAM, 'RateApplicablePercent')}")) or "0")
        tax_line = (net_line * rate / Decimal("100")).quantize(Decimal("0.01"), ROUND_HALF_UP)
        gross_line = net_line + tax_line
        unit_price = (net_line / quantity).quantize(Decimal("0.0001"), ROUND_HALF_UP)
        items.append({
            "position": pos,
            "description": desc,
            "unit": unit,
            "quantity": quantity,
            "unit_price": unit_price,
            "tax_rate": rate,
            "net_amount": net_line,
            "tax_amount": tax_line,
            "gross_amount": gross_line,
        })

    buyer_vat = _find_buyer_vat(root)
    return {
        "number": number,
        "issue_date": issue_date,
        "due_date": due_date,
        "delivery_date": delivery_date,
        "payment_terms": payment_terms,
        "notes": notes,
        "net_total": net,
        "tax_total": tax,
        "gross_total": gross,
        "tax_category": category,
        "buyer_vat": buyer_vat,
        "items": items,
        "xml_text": xml_path.read_text(encoding="utf-8"),
    }


def einspielen(nummern: list[str], *, aus_altem_system: bool = False) -> None:
    settings = get_settings()
    xml_dir = settings.storage_path / "xml"
    pdf_dir = settings.storage_path / "pdfs"
    db = SessionLocal()
    try:
        for num in nummern:
            xml_path = xml_dir / f"{num}.xml"
            pdf_path = pdf_dir / f"{num}.pdf"
            if not xml_path.is_file():
                print(f"FEHLER: {xml_path} fehlt")
                continue
            if not pdf_path.is_file():
                print(f"FEHLER: {pdf_path} fehlt")
                continue
            if db.query(Invoice).filter(Invoice.invoice_number == num).first():
                print(f"übersprungen: {num} existiert bereits")
                continue

            data = _parse(xml_path)
            customer = None
            if data["buyer_vat"]:
                customer = db.query(Customer).filter(Customer.vat_id == data["buyer_vat"]).first()
            if customer is None:
                print(f"FEHLER: {num} — kein Kunde mit USt-IdNr. {data['buyer_vat']}")
                continue

            inv = Invoice(
                invoice_number=data["number"],
                customer_id=customer.id,
                issue_date=data["issue_date"],
                due_date=data["due_date"],
                delivery_date=data["delivery_date"],
                payment_terms=data["payment_terms"],
                notes=data["notes"],
                currency="EUR",
                net_total=data["net_total"],
                tax_total=data["tax_total"],
                gross_total=data["gross_total"],
                status="issued",
                zugferd_profile="EN16931",
                tax_category=data["tax_category"],
                zugferd_xml=data["xml_text"],
                pdf_filename=f"{num}.pdf",
                archive_until=berechne_archive_until(data["issue_date"]),
            )
            db.add(inv)
            db.flush()
            for row in data["items"]:
                db.add(InvoiceItem(invoice_id=inv.id, **row))
            db.commit()
            print(f"eingespielt: {num} → Kunde {customer.name} ({customer.customer_number})")
            if aus_altem_system:
                from scripts.beleg_migration_nachziehen import nachziehen
                nachziehen([num])
    finally:
        db.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Finalisierte Belege aus XML/PDF einspielen")
    parser.add_argument("nummern", nargs="*", help="Rechnungsnummern (z. B. Z-2026-002)")
    parser.add_argument(
        "--alt-system",
        action="store_true",
        help="Versand und Bezahlt aus altem Abgehakt nachziehen (Migration)",
    )
    args = parser.parse_args()
    nums = args.nummern or ["Z-2026-002", "Z-2026-004"]
    einspielen(nums, aus_altem_system=args.alt_system)
