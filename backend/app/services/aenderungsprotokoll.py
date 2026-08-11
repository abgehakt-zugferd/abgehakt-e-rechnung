"""Das Änderungsprotokoll einer Rechnung, lesbar für Menschen (#154).

`audit_log` hält die Rohdaten: `insert`/`update`/`delete` plus zwei JSON-Abzüge.
Das ist die richtige Form zum Aufbewahren und die falsche zum Anzeigen. Hier wird
daraus je Zeile ein Satz, der ohne Erklärung verständlich ist.

Der Dienst **liest nur**. Er schreibt nichts und ändert nichts; `audit_log` bleibt
unangetastet vollständig, und der GoBD-Export zeigt weiterhin jede einzelne Zeile.

Was er tut, ist gruppieren, nicht unterschlagen: Ein Vorgang, der in einer
Transaktion mehrere Zeilen schreibt, wird als EIN Vorgang angezeigt. Der Unterschied
ist wesentlich — ein Ereignis zu verschweigen wäre falsch, ein Ereignis doppelt zu
zeigen aber auch. Siehe `protokoll_fuer`.
"""
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.invoice import AuditLog

# Wie viele Einträge die Detailseite höchstens lädt. Das Protokoll wächst nur und
# wird nie aufgeräumt; ohne Grenze würde eine alte Rechnung die Seite ausbremsen.
# Wer mehr braucht, zieht den GoBD-Export, der ist vollständig.
HOECHSTZAHL = 50

# Statuswechsel sind das, was Nutzer eigentlich wissen wollen. Schlüssel ist der
# NEUE Status; der alte spielt keine Rolle, weil die Statusmaschine ohnehin nur
# einen Weg dorthin zulässt (`services/invoice_guard.py`).
STATUSWECHSEL = {
    "issued": "Finalisiert",
    "paid": "Als bezahlt vermerkt",
    "cancelled": "Storniert",
    "discarded": "Entwurf verworfen",
    "draft": "Entwurf zurückgeholt",
}

FELDNAMEN = {
    "invoice_number": "Rechnungsnummer",
    "customer_id": "Kunde",
    "issue_date": "Rechnungsdatum",
    "due_date": "Fälligkeitsdatum",
    "delivery_date": "Leistungsdatum",
    "payment_terms": "Zahlungsbedingungen",
    "buyer_reference": "Referenz des Kunden",
    "notes": "Anmerkungen",
    "net_total": "Nettobetrag",
    "tax_total": "Steuerbetrag",
    "gross_total": "Bruttobetrag",
    "status": "Status",
    "tax_category": "Steuertyp",
    "zugferd_profile": "ZUGFeRD-Profil",
    "datev_sent_at": "DATEV-Versand",
    "archive_until": "Aufbewahrung bis",
    "pdf_filename": "PDF-Datei",
    "zugferd_xml": "ZUGFeRD-XML",
    "logo_variant": "Logo",
    "original_invoice_id": "Bezug zur Originalrechnung",
    "invoice_type": "Rechnungsart",
}

# Technische Spalten, die sich bei jeder Änderung mitbewegen. Sie als „geändertes
# Feld" aufzuführen würde jede Zeile mit Rauschen füllen.
STILLE_FELDER = {"updated_at", "created_at"}


@dataclass
class Protokollzeile:
    zeitpunkt: datetime
    vorgang: str
    felder: list[str] = field(default_factory=list)


def _geaenderte_felder(alt: dict | None, neu: dict | None) -> list[str]:
    if not neu:
        return []
    alt = alt or {}
    namen = []
    for schluessel, wert in neu.items():
        if schluessel in STILLE_FELDER or alt.get(schluessel) == wert:
            continue
        namen.append(FELDNAMEN.get(schluessel, schluessel))
    return namen


def _beschreibe(eintrag: AuditLog) -> Protokollzeile:
    alt = eintrag.old_values or {}
    neu = eintrag.new_values or {}

    if eintrag.action == "insert":
        return Protokollzeile(eintrag.changed_at, "Entwurf angelegt")

    if eintrag.action == "delete":
        # Kommt im Betrieb nicht vor (Guard und DB-Trigger verbieten es). Steht
        # hier trotzdem: fiele beides aus, wäre genau das die Zeile, die zählt.
        return Protokollzeile(eintrag.changed_at, "Gelöscht")

    neuer_status = neu.get("status")
    if neuer_status and neuer_status != alt.get("status"):
        vorgang = STATUSWECHSEL.get(neuer_status, f"Status auf {neuer_status} gesetzt")
        return Protokollzeile(eintrag.changed_at, vorgang)

    if neu.get("datev_sent_at") and not alt.get("datev_sent_at"):
        return Protokollzeile(eintrag.changed_at, "An DATEV gesendet")

    felder = _geaenderte_felder(alt, neu)
    return Protokollzeile(eintrag.changed_at, "Bearbeitet", felder)


def protokoll_fuer(db: Session, invoice_id) -> list[Protokollzeile]:
    """Die Einträge zu genau dieser Rechnung, neueste zuerst.

    Gefiltert wird über Tabelle UND Datensatz: `record_id` allein wäre hier
    zufällig richtig und beim nächsten Modell falsch. Genau dieses Paar deckt der
    zusammengesetzte Index in `AuditLog` ab.

    **Das Anlegen schreibt zwei Zeilen, ist aber ein Vorgang.** `create_invoice`
    fügt die Rechnung ein, holt sich per `flush()` die ID und setzt danach Summen
    und Aufbewahrungsfrist — ein `INSERT` und ein `UPDATE` in derselben
    Transaktion. Ungruppiert stand deshalb neben „Entwurf angelegt" eine Zeile
    „Bearbeitet: Nettobetrag, Bruttobetrag, Aufbewahrung bis" über eine
    Bearbeitung, die nie stattgefunden hat. Auf einer Seite, die gerade die Frage
    „war jemand an meiner Rechnung?" beantworten soll, ist das die
    unangenehmste Art von falsch.

    Erkannt am Zeitpunkt: `changed_at` ist ein `now()` der Datenbank, und das ist
    in Postgres der Beginn der Transaktion — für alle Zeilen einer Transaktion
    derselbe Wert. Eine spätere echte Bearbeitung läuft in einer eigenen
    Transaktion und behält ihre Zeile.
    """
    eintraege = (
        db.query(AuditLog)
        .filter(AuditLog.table_name == "invoices",
                AuditLog.record_id == str(invoice_id))
        .order_by(AuditLog.changed_at.desc())
        .limit(HOECHSTZAHL)
        .all()
    )
    anlage = {e.changed_at for e in eintraege if e.action == "insert"}
    return [
        _beschreibe(e) for e in eintraege
        if not (e.action == "update" and e.changed_at in anlage)
    ]
