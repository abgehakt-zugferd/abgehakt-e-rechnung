"""Belegartgrenze für manuelle Herleitungen (#251)."""
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException

from app.models.invoice import Invoice
from app.services.belegart import ist_honorargutschrift


def pruefe_herleitung_belegart(raw_items, invoice_type, *, bestand: Invoice | None = None) -> None:
    """Altwerte dürfen an derselben Positionsnummer bleiben oder entfernt werden.

    So bleiben Textkorrekturen an alten Entwürfen möglich, ohne neue falsche
    Herleitungen zuzulassen oder vorhandene Daten still zu löschen. Da das
    Formular keine Positions-IDs liefert, gilt die Positionsnummer als Bezug.
    Die bestehende Rechenprobe bleibt zusätzlich wirksam. Ein Typwechsel aus
    einer Honorargutschrift begründet keinen Bestandsschutz; deshalb muss die
    Prüfung VOR der Änderung der gespeicherten Belegart stattfinden.
    Übergabebelege werden vom Aufrufer ausgenommen und weiterhin gebunden.
    """
    if ist_honorargutschrift(invoice_type):
        return
    alte = {}
    if bestand is not None and not ist_honorargutschrift(bestand.invoice_type):
        alte = {p.position: (p.basis_netto, p.satz) for p in bestand.items}
    for nr, raw in enumerate(raw_items, 1):
        werte = [str(raw.get(feld) if raw.get(feld) is not None else "").strip()
                 for feld in ("basis_netto", "satz")]
        if not any(werte):
            continue
        try:
            paar = tuple(Decimal(wert) for wert in werte)
            if all(wert.is_finite() for wert in paar) and paar == alte.get(nr):
                continue
        except InvalidOperation:
            pass
        raise HTTPException(400,
            f"Position {nr}: Neue oder geänderte Herleitungswerte sind nur bei Honorargutschriften erlaubt. "
            "Vorhandene Werte können unverändert bleiben oder beide entfernt werden.")
