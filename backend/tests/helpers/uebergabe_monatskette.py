"""Helfer fuer Szenariotests der Uebergabekette ueber Monatslieferungen (#226)."""

from __future__ import annotations

import hashlib
import uuid
from urllib.parse import parse_qs, urlparse

from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.models.invoice import Invoice
from tests.helpers.uebergabe import (
    PARTNER_A,
    auftrag,
    beleg,
    rechnungsauftrag,
)

RICHTUNG = "tantiemen-app-nach-abgehakt"


def schalter(pg_session, aktiv=True):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.beleg_integration_aktiv = aktiv
    pg_session.commit()


def plattform_kunde(pg_session, kennung=PARTNER_A, **felder):
    """Kunde fuer Rechnungsauftraege (AE) und Abrechnungsauftraege (Gutschrift)."""
    angaben = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Markt GmbH",
        address_line1="Platz 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        auftrag_steuer="AE",
        vat_id="NL000000000B01",
        gutschriftempfaenger=True,
        ust_status="regelbesteuert",
        tax_number="99/999/99999",
        kopftext="Abrechnungsmonat {leistungsmonat}.",
        fusstext="Einzelaufstellung liegt bei.",
        zahlungshinweis="Zahlung folgt dem Auszahlungsbericht.",
    )
    angaben.update(felder)
    kunde = Customer(**angaben)
    kunde.id = uuid.UUID(str(kennung))
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def rechnungs_beleg(
    signieren,
    *,
    auftragsschluessel: str,
    erzeugt_am: str,
    vorgaenger_hash=None,
    beleg_id=None,
    netto="171.34",
):
    """Ein signierter Rechnungsauftrag mit eigenen Schluesseln und Zeitstempel."""
    nutzlast = rechnungsauftrag(
        auftragsschluessel=auftragsschluessel,
        summe={"netto": netto},
        positionen=[
            {
                "nr": 1,
                "gruppe": "Gruppe A",
                "bezeichnung": "Nutzungsrechte A",
                "netto": netto,
            },
        ],
        grundlagen=[{
            "quelle": "abrechnungsbericht",
            "beleg_sha256": "1a" * 32,
            "leistungsperiode": auftragsschluessel.split(":")[1],
            "netto": netto,
        }],
    )
    return beleg(
        signieren,
        nutzlast,
        nutzlast_art="rechnungsauftrag",
        beleg_id=beleg_id or str(uuid.uuid4()),
        erzeugt_am=erzeugt_am,
        vorgaenger_hash=vorgaenger_hash,
    )


def abrechnungs_beleg(signieren, *, erzeugt_am: str, vorgaenger_hash, beleg_id=None):
    return beleg(
        signieren,
        auftrag(),
        nutzlast_art="abrechnungsauftrag",
        beleg_id=beleg_id or str(uuid.uuid4()),
        erzeugt_am=erzeugt_am,
        vorgaenger_hash=vorgaenger_hash,
    )


def ablegen(ordner, name: str, roh: bytes) -> bytes:
    (ordner / name).write_bytes(roh)
    return roh


def anlegen(client, name: str):
    return client.post(f"/uebergaben/{name}/rechnung-anlegen")


def fehler_aus(antwort) -> str:
    return parse_qs(urlparse(antwort.headers["location"]).query).get("fehler", [""])[0]


def sha_von(roh: bytes) -> str:
    return hashlib.sha256(roh).hexdigest()


def entwurf_merkmal(inv: Invoice) -> tuple:
    """Nummer, Summe, Status - was Monat-1-Entwuerfe nach Monat 2 behalten muessen."""
    return (inv.invoice_number, inv.net_total, inv.status)
