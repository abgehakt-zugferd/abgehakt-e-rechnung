"""ORM-Fabriken fuer die Abrechnungsaufstellung (Bauschritt 7a, Entscheidung 8).

Eigene Datei neben tests/factories.py: Die Aufstellung ist KEINE Rechnung und
teilt sich keine Spaltennamen mit Invoice (nummer statt invoice_number,
brutto/quellensteuer/netto statt net/tax/gross). Die Rechnungs-Fabriken
sollen nicht fuer sie wachsen — beide Fabrik-Seiten bleiben getrennt wie die
Modelle.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.models.aufstellung import Aufstellung, AufstellungAnlage
from app.services.auftragsschluessel import belegen
from tests.factories import orm_customer

# Der einzige Medientyp, den der Leser § 8b fuer Anlagen zulaesst.
XLSX_MEDIENTYP = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def orm_anlage(quelle="abrechnungsbericht", **over):
    """Eine der genau zwei xlsx-Anlagen einer Aufstellung (§ 8b).

    sha256-Form: 64 Kleinhex-Zeichen; der Platzhalter erfuellt den DB-CHECK
    der Form, der Inhalt ist fuer diese Fabrik gleichgueltig.
    """
    kw = dict(
        dateiname=f"{quelle}.xlsx",
        sha256="a" * 64,
        groesse=2048,
        medientyp=XLSX_MEDIENTYP,
    )
    kw.update(over)
    return AufstellungAnlage(quelle=quelle, **kw)


def orm_aufstellung(schluessel=None, *, status="draft", anlagen=(), **over):
    """Aufstellung mit gueltigen Werten: EUR ohne Umrechnung, Summe stimmig.

    Eigene Nummer je Aufruf, weil mehrere Aufstellungen in einem Test
    nebeneinander bestehen muessen und nummer unique ist. Nachweis und Sperre
    setzt die Fabrik ueber auftragsschluessel.belegen — dieselbe Stelle wie
    die Anwendung; ein belegter Schluessel soll in den Fabriken nicht
    moeglich sein.
    """
    kw = dict(
        nummer=f"AA-{uuid.uuid4().hex[:6]}",
        leistung_von=date(2026, 9, 1),
        leistung_bis=date(2026, 9, 30),
        zahlungsnummer="4711",
        zahlungsdatum=date(2026, 9, 30),
        waehrung="EUR",
        brutto=Decimal("1000.00"),
        quellensteuer=Decimal("80.00"),
        netto=Decimal("920.00"),
        status=status,
    )
    kw.update(over)
    a = Aufstellung(**kw)
    a.customer = over.get("customer") or orm_customer()
    if a.customer.customer_number is None:
        # orm_customer setzt keine customer_number, die Spalte ist NOT NULL.
        a.customer.customer_number = f"K-7A-{uuid.uuid4().hex[:8]}"
    a.anlagen = list(anlagen)
    if schluessel is not None:
        # Noch transient (keine Session): belegen setzt nur, die Pruefung der
        # beiden Tabellen braucht eine Session und laeuft beim Aufrufer.
        belegen(a, schluessel)
    return a


def speichere_aufstellung(pg_session, **over):
    """Committete Aufstellung mit beiden Anlagen (§ 8b: genau zwei).

    Fuer die Router- und Finalisieren-Tests (7c): Sie brauchen eine Zeile
    mit id in der DB, kein transientes Objekt. Kann jede Fabrik-
    Option uebernehmen, `anlagen` stehen beide standardmaessig.
    """
    kw = dict(anlagen=[orm_anlage("abrechnungsbericht"),
                       orm_anlage("zahlungsbericht", sha256="b" * 64, groesse=4096)])
    kw.update(over)
    a = orm_aufstellung(**kw)
    pg_session.add(a)
    pg_session.commit()
    return a
