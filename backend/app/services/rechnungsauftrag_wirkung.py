"""Aus einem angenommenen rechnungsauftrag wird ein Entwurf (§ 8a, Bauschritt 4b).

Getrennt vom Lesen wie die Wirkung der 389 (abrechnungsauftrag_wirkung.py):
Dort wird beurteilt, hier wird geschrieben, und erst der Knopf ALS RECHNUNG
ANLEGEN ruft diese Stelle auf. Was entsteht, ist ein ENTWURF der Standard-
rechnung (380) - Finalisieren und Versenden bleiben Handgriffe des Menschen.

Die Steuer steht nicht im Auftrag, sondern am Kunden (Festlegung 13):
`auftrag_steuer` AE verlangt die USt-IdNr. des Kunden, sonst entsteht nichts
- die Steuer wird nicht geraten. Die Betraege, der Beteiligte, der Zeitraum
und die Gruppen stammen aus dem signierten Auftrag und sind am Entwurf
gebunden (belegsperre.gilt, Nachweis ueber die beiden Belegspalten). Kopf-
und Fusstext, Zahlungshinweis und Belegsprache werden aus dem Kundenstamm
KOPIERT (Festlegung 15); die Bemerkung bleibt leer, denn die Herkunft steht
im Beleg.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.invoice import Invoice, InvoiceItem
from app.services import auftragsschluessel
from app.services.abrechnungsauftrag_wirkung import (
    BelegSchonVerarbeitet,
    WirkungFehler,
    _datum,
    _kunde,
)
from app.services.archive_frist import berechne_archive_until
from app.services.invoice_number import generate_next_invoice_number
from app.services.kundenvorgaben import entwurfs_vorbelegung
from app.services.uebergabe_befund import Belegurteil
from app.services.uebergabe_eingang import merken
from app.zeit import heute, kalendertag


def entwurf_anlegen(
    db: Session,
    urteil: Belegurteil,
    *,
    company: Optional[Company] = None,
    dateiname: Optional[str] = None,
) -> Invoice:
    """Legt den Entwurf an und merkt den Beleg. Committet nicht.

    Alles oder nichts wie bei entwuerfe_anlegen: entweder steht der Entwurf
    mit allen Positionen, oder der Aufrufer rollt zurueck.
    """
    if not urteil.angenommen:
        raise WirkungFehler("Aus einem abgelehnten Beleg entsteht nichts.")
    if urteil.bereits_verarbeitet:
        raise BelegSchonVerarbeitet(urteil.beleg_id or urteil.beleg_sha256)
    if not urteil.nutzlast:
        raise WirkungFehler("Der Beleg traegt keine Nutzlast.")

    if company is None:
        company = db.query(Company).filter(Company.id == 1).first()
        if company is None:
            raise WirkungFehler("Firmendaten sind nicht eingerichtet.")

    nutzlast = urteil.nutzlast
    kunde = _kunde(db, nutzlast["kunde"]["partner_id"])

    # Vorbedingung (Festlegung 13): Kategorie und Vermerk kommen aus DER
    # Vorgabe am Kunden, nicht vom Draht. AE verlangt die USt-IdNr. des
    # Kunden - der Vermerk (AE_HINWEIS, BT-120) druckt das System, die
    # Kennung des Empfaengers (BT-48) muss dafuer tragbar sein. Ohne Vorgabe
    # entsteht kein Entwurf; das Muster ist der ungeklaerte Steuerstatus
    # der 389, und die Meldung nennt beide moeglichen Gruende.
    if (kunde.auftrag_steuer or "") != "AE" or not (kunde.vat_id or "").strip():
        raise WirkungFehler(
            "Am Kunden fehlt die Steuervorgabe für Aufträge (AE) bzw. die USt-IdNr."
        )

    zeitraum = nutzlast["leistungszeitraum"]
    von = _datum(zeitraum["von"])
    bis = _datum(zeitraum["bis"])

    # Ausstellungsdatum nur vorlaeufig (Festlegung 14): Es zaehlt der
    # Kalendertag von erzeugt_am in Europe/Berlin (app.zeit.kalendertag)
    # wie bei der 389, aber gestellt wird die Rechnung erst beim
    # Finalisieren, das das Datum auf heute setzt. Ohne Zahlungshinweis
    # ist der Entwurf 14 Tage spaeter faellig - dieselbe Voreinstellung
    # wie bei entwuerfe_anlegen; mit Hinweis entfaellt BT-9 (Entscheidung 4).
    ausstellung = kalendertag(urteil.erzeugt_am) if urteil.erzeugt_am else heute()
    vorgabe = entwurfs_vorbelegung(kunde, von, bis)

    entwurf = Invoice(
        invoice_number=generate_next_invoice_number(db, issue_date=ausstellung),
        customer_id=kunde.id,
        issue_date=ausstellung,
        due_date=None if vorgabe.zahlungshinweis else ausstellung + timedelta(days=14),
        service_period_start=von,
        service_period_end=bis,
        payment_terms=vorgabe.zahlungshinweis,
        kopftext=vorgabe.kopftext,
        fusstext=vorgabe.fusstext,
        # NULL heisst die Sprache der Firma wie bisher; die Vorgabe des
        # Kunden schlaegt nur, wenn er eine traegt (Festlegung 15).
        document_language=vorgabe.belegsprache or "de",
        # invoice_type None ist die Standardrechnung (380) - derselbe
        # Typcode, den der Leser im Auftrag bereits erzwingt.
        invoice_type=None,
        tax_category="AE",
        status="draft",
        uebergabe_beleg_id=urteil.beleg_id,
        uebergabe_beleg_sha256=urteil.beleg_sha256,
    )
    auftragsschluessel.belegen(entwurf, nutzlast["auftragsschluessel"])
    db.add(entwurf)
    db.flush()

    netto_summe = Decimal("0")
    for lfd, position in enumerate(
        sorted(nutzlast["positionen"], key=lambda p: p["nr"]), 1,
    ):
        # Der Leser erzwingt die Geldform (genau zwei Nachkommastellen),
        # deshalb wird hier nicht gerundet - wie bei der 389 (#163). Ein
        # negativer Einzelpreis ist bei einer 380 aus einem Auftrag
        # zulaessig (Festlegung 11, pruefregeln/positionen.py); in der XML
        # traegt die Menge das Vorzeichen (BR-27, zugferd_xml/).
        netto = Decimal(str(position["netto"]))
        db.add(InvoiceItem(
            invoice_id=entwurf.id,
            position=lfd,
            description=str(position.get("bezeichnung", "")).strip(),
            gruppe=position.get("gruppe"),
            # Einheit wie bei der 389 aus dem Auftrag: Der Betrag ist eine
            # Summe aus dem Abrechnungsbericht, keine gemessene Menge.
            unit="Pauschal",
            quantity=Decimal("1"),
            unit_price=netto,
            tax_rate=Decimal("0"),
            net_amount=netto,
            tax_amount=Decimal("0"),
            gross_amount=netto,
        ))
        netto_summe += netto

    entwurf.net_total = netto_summe
    entwurf.tax_total = Decimal("0")
    entwurf.gross_total = netto_summe
    entwurf.archive_until = berechne_archive_until(entwurf.issue_date)

    merken(db, urteil, dateiname=dateiname)
    return entwurf
