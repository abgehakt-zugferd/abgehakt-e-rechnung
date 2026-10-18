"""Storno-Invarianten, aufgerufen vom zentralen Aufstellungs-Guard."""
from sqlalchemy import select
from sqlalchemy.orm.attributes import get_history

from app.models.aufstellung import Aufstellung, AufstellungAnlage
from app.services.aufstellung_storno import KOPIEFELDER


def pruefe_storno(session, obj, fehler):
    if obj.storniert_id is None:
        return
    original = session.get(Aufstellung, obj.storniert_id)
    if original is None or original.storniert_id is not None or original.id == obj.id:
        raise fehler("Ein Storno braucht ein Original und kann selbst nicht storniert werden.")
    if obj.status == "cancelled":
        raise fehler("Ein Storno kann nicht storniert werden.")
    if obj.anlagen:
        raise fehler("Ein Storno traegt keine eigenen Anlagen; es verweist auf das Original.")
    if any(getattr(obj, feld) != getattr(original, feld) for feld in KOPIEFELDER):
        raise fehler("Beträge, Kunde und Zeitraum des Stornos muessen dem Original entsprechen.")
    if obj.auftragsschluessel_offen is not None:
        raise fehler("Ein Storno darf keinen Auftragsschluessel sperren.")
    if obj.status == "issued":
        if original.status != "cancelled" or original.auftragsschluessel_offen is not None:
            raise fehler("Das finalisierte Storno muss das Original aufheben und seinen Schlüssel freigeben.")
    elif obj.status != "discarded" and original.status != "issued":
        raise fehler("Ein Stornoentwurf braucht ein gestelltes Original.")


def pruefe_aufhebung(session, original, fehler):
    # Pending-Status zuerst lesen: Im selben Flush steht das Storno in der
    # Datenbank noch als draft. Nur eine DB-Abfrage wuerde den legitimen
    # gemeinsamen Uebergang ablehnen. Persistierte Zeilen ergaenzen die Menge.
    kandidaten = set(session.new) | set(session.dirty)
    kandidaten.update(session.scalars(select(Aufstellung).where(
        Aufstellung.storniert_id == original.id,
    )))
    gestellt = any(isinstance(s, Aufstellung) and s.storniert_id == original.id
                    and s.status == "issued" and s.ausstellungsdatum is not None
                    and s.pdf_filename for s in kandidaten)
    if original.storniert_id or not gestellt or original.auftragsschluessel_offen is not None:
        raise fehler("Aufheben ist nur durch ein finalisiertes Storno mit Schlüsselfreigabe erlaubt.")


def pruefe_storno_anlage(session, anlage: AufstellungAnlage, fehler):
    parent = anlage.__dict__.get("aufstellung")
    if parent is None and anlage.aufstellung_id is not None:
        parent = session.get(Aufstellung, anlage.aufstellung_id)
    if parent is not None and parent.storniert_id is not None:
        raise fehler("Ein Storno darf keine eigenen Anlagen tragen.")


def pruefe_stornobezug(obj, fehler):
    hist = get_history(obj, "storniert_id")
    if hist.has_changes() or get_history(obj, "original").has_changes():
        raise fehler("Der Originalbezug eines gespeicherten Stornos ist unveränderlich.")
