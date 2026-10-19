"""Verwerfen und Zurückholen mit Auftragsschlüssel- und Stornoprüfung."""
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.aufstellung import Aufstellung
from app.services import auftragsschluessel


def _storno_pruefen(db, a):
    if not a.storniert_id:
        return
    original = db.query(Aufstellung).filter(
        Aufstellung.id == a.storniert_id,
    ).populate_existing().with_for_update().one()
    if original.status != "issued" or db.query(Aufstellung.id).filter(
        Aufstellung.storniert_id == original.id, Aufstellung.id != a.id,
        Aufstellung.status != "discarded",
    ).first():
        raise HTTPException(400, "Das Original ist nicht mehr stornierbar oder hat bereits ein Storno.")


def wechseln(db, a, zurueckholen=False):
    erwartet = "discarded" if zurueckholen else "draft"
    if a.status != erwartet:
        raise HTTPException(400, f"Dieser Handgriff braucht den Status {erwartet}.")
    try:
        if zurueckholen:
            _storno_pruefen(db, a)
            if a.auftragsschluessel is not None and not a.storniert_id:
                belegt = auftragsschluessel.dokument_zu(db, a.auftragsschluessel)
                if belegt is not None:
                    raise HTTPException(400, f"Zu diesem Auftrag gibt es inzwischen einen anderen Beleg: {belegt}.")
                auftragsschluessel.belegen(a, a.auftragsschluessel)
            a.status = "draft"
        else:
            a.status = "discarded"
            auftragsschluessel.freigeben(a)
        db.commit()
    except auftragsschluessel.SchluesselBelegtError as fehler:
        db.rollback()
        raise HTTPException(400, str(fehler)) from fehler
    except IntegrityError as fehler:
        db.rollback()
        # Die Vorabprüfung ist freundlich, die partiellen Unique-Indizes
        # fangen konkurrierendes Zurückholen verbindlich beim Commit ab.
        name = getattr(getattr(fehler.orig, "diag", None), "constraint_name", None)
        if name not in {"uq_aufstellungen_auftragsschluessel_offen",
                        "uq_aufstellungen_ein_aktives_storno_pro_original"}:
            raise
        raise HTTPException(400, "Inzwischen besteht ein anderer Beleg zu diesem Auftrag oder Storno.") from fehler
