"""Wann die Ersteinrichtung abgeschlossen ist (#205).

Eine Quelle fuer Meldung, Pflichtangaben und das Flag `setup_completed_at`.
`POST /setup` und `POST /settings/firma` pruefen dieselben Pflichtangaben;
nur bei Erfuellung wird das Flag gesetzt, nie zurueckgenommen.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.models.company import Company
from app.services.pflichtangaben import pflichtangaben

ERSTEINRICHTUNG_OFFEN_MELDUNG = (
    "Die Ersteinrichtung ist nicht abgeschlossen. Bitte unter /setup abschließen."
)

# Dieselben Adressfelder, die POST /setup als Pflicht verlangt.
ADRESS_PFLICHTFELDER = ("name", "address_line1", "zip_code", "city")


def ist_eingerichtet(company: Company | None) -> bool:
    """Abgeschlossen heisst: Flag gesetzt. Feldinhalte allein genuegen nicht."""
    return bool(company and company.setup_completed_at is not None)


def einrichtung_luecke(company: Company) -> str | None:
    """Fehlermeldung, wenn die Pflichtangaben von POST /setup fehlen."""
    if any(not (getattr(company, feld) or "").strip() for feld in ADRESS_PFLICHTFELDER):
        return "Bitte Firmenname und vollständige Anschrift angeben."
    if not (company.tax_number or "").strip() and not (company.vat_id or "").strip():
        return "Steuernummer oder USt-IdNr. ist für § 14 UStG erforderlich."
    if (luecke := pflichtangaben(company).luecke()):
        return f"Pflichtangaben für Rechnungen fehlen: {luecke}."
    return None


def einrichtung_abschliessen(company: Company) -> None:
    """Setzt das Abschlussflag. Aufrufer hat die Pflicht zuvor geprueft."""
    company.setup_completed_at = datetime.now(timezone.utc)


def einrichtung_nachziehen(company: Company) -> None:
    """Settings→Firma: schliesst ab, wenn Pflicht erfuellt; setzt nie zurueck."""
    if company.setup_completed_at is not None:
        return
    if einrichtung_luecke(company) is None:
        einrichtung_abschliessen(company)
