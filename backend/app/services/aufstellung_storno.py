"""Storno als eigener Entwurf; Aufhebung erst mit seinem archivierten PDF."""
from sqlalchemy.orm import Session

from app.models.aufstellung import Aufstellung
from app.services.auftragsschluessel import freigeben
from app.services.invoice_number import generate_next_aufstellung_number

# Identische Werte, kein negatives Gegenrechnen: Dies ist keine Rechnung.
KOPIEFELDER = (
    "customer_id", "leistung_von", "leistung_bis", "zahlungsnummer", "zahlungsdatum",
    "waehrung", "brutto", "quellensteuer", "netto", "kurs", "zahlbetrag_eur",
)


class StornoFehler(ValueError):
    """Das Original ist nicht stornierbar."""


def entwurf_anlegen(db: Session, original: Aufstellung) -> Aufstellung:
    # Original sperren, bevor Existenzpruefung und Nummernvergabe laufen.
    # Der partielle Index sichert auch Skripte und das Zurueckholen ab.
    original = db.query(Aufstellung).filter(Aufstellung.id == original.id).populate_existing().with_for_update().one()
    if original.status != "issued" or original.storniert_id is not None:
        raise StornoFehler("Nur eine gestellte Aufstellung, die selbst kein Storno ist, kann storniert werden.")
    if db.query(Aufstellung.id).filter(
        Aufstellung.storniert_id == original.id, Aufstellung.status != "discarded",
    ).first():
        raise StornoFehler("Zu dieser Aufstellung besteht bereits ein nicht verworfenes Storno.")
    s = Aufstellung(
        nummer=generate_next_aufstellung_number(db), status="draft",
        storniert_id=original.id,
        **{feld: getattr(original, feld) for feld in KOPIEFELDER},
    )
    db.add(s)
    db.flush()
    return s


def original_aufheben(db: Session, storno: Aufstellung) -> None:
    if storno.storniert_id is None:
        return
    original = db.query(Aufstellung).filter(
        Aufstellung.id == storno.storniert_id,
    ).populate_existing().with_for_update().one()
    if original.status != "issued" or original.storniert_id is not None:
        raise StornoFehler("Das Original ist nicht mehr stornierbar.")
    original.status = "cancelled"
    freigeben(original)
