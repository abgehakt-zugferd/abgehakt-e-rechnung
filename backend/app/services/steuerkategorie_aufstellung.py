"""Umsatz je Steuerkategorie und Steuersatz (Issue #256).

Die Uebersicht addiert Netto und Umsatzsteuer, ohne nach Steuerkategorie zu
trennen. Umsatzsteuer-Voranmeldung und Zusammenfassende Meldung brauchen die
Umsaetze getrennt: Standardsatz, Reverse Charge, innergemeinschaftliche
Lieferung, nicht steuerbar, steuerfrei. Diese Aufstellung liefert die Zeilen;
sie ordnet nichts amtlichen Kennziffern zu und exportiert nichts.

Belegmenge und Zeitlogik sind die der Kennzahlen: `beleg_bedingungen` und
`gutschrift_bedingungen` sind ihre einzigen Quellen. Gutschriften mindern die
Zeile ihrer eigenen Kategorie und ihres eigenen Satzes.

Entscheidung zur Ebene: Die Kategorie liegt am Beleg (`Invoice.tax_category`),
der Satz an der Position (`InvoiceItem.tax_rate`); ein Beleg ohne Belegabzug
darf gemischte Saetze tragen. Die Aufteilung je Satz kommt deshalb aus den
Positionen. Damit die Zeilen trotzdem genau in den Kopfsummen aufgehen, gilt:
  * Mit Belegabzug (BG-20) ist der Satz einheitlich; die Kopfsummen (Steuerbasis
    und Steuer auf der verminderten Basis) gehen unveraendert auf diesen Satz.
  * Sonst zaehlen die Positionssummen. Weicht die Kopfsumme davon ab oder fehlen
    Positionen (Altbestand), steht der Rest in einer Zeile ohne Satz (None).
So ist die Summe der Zeilen immer die Summe der Kopfsummen, wie sie die
Kennzahlen addieren.

Waehrung: Zeilen tragen ihre Waehrung. Nur EUR-Zeilen entsprechen
Nettoumsatz und schuldiger Umsatzsteuer; die bestehenden Kennzahlen addieren
Betraege ohne Ruecksicht auf die Waehrung, ergeben also EUR plus die nominalen
Betraege fremder Waehrung. Fremde Waehrungen werden nicht umgerechnet.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy.orm import Session, selectinload

from app.models.invoice import Invoice
from app.services.dashboard_kennzahlen import UMSATZ_BELEGARTEN, beleg_bedingungen
from app.services.storno_wirkung import gutschrift_bedingungen

_CENT = Decimal("0.01")
_NULL = Decimal("0.00")


# Klartext zu den Kategoriecodes (UNTDID 5305) fuer die Anzeige.
BEZEICHNUNG = {
    "S": "Steuerpflichtig", "Z": "Nullsatz", "E": "Steuerfrei",
    "AE": "Reverse Charge", "K": "Innergemeinschaftliche Lieferung",
    "G": "Ausfuhr", "O": "Nicht steuerbar",
    "L": "Kanarische Inseln", "M": "Ceuta und Melilla",
}


@dataclass(frozen=True, slots=True)
class Steuerzeile:
    kategorie: str
    satz: Decimal | None
    waehrung: str
    netto: Decimal
    steuer: Decimal

    @property
    def bezeichnung(self) -> str:
        return BEZEICHNUNG.get(self.kategorie, self.kategorie)


def _anteile(beleg: Invoice) -> dict[Decimal | None, tuple[Decimal, Decimal]]:
    """Netto und Steuer eines Belegs je Satz; die Summe ist immer die Kopfsumme."""
    je_satz: dict[Decimal | None, list[Decimal]] = defaultdict(lambda: [_NULL, _NULL])
    for item in beleg.items:
        je_satz[item.tax_rate][0] += item.net_amount
        je_satz[item.tax_rate][1] += item.tax_amount
    if beleg.abzug_betrag is not None and len(je_satz) == 1:
        return {next(iter(je_satz)): (beleg.net_total, beleg.tax_total)}
    rest_netto = beleg.net_total - sum((n for n, _ in je_satz.values()), _NULL)
    rest_steuer = beleg.tax_total - sum((s for _, s in je_satz.values()), _NULL)
    ergebnis = {satz: (n, s) for satz, (n, s) in je_satz.items()}
    if rest_netto or rest_steuer or not ergebnis:
        ergebnis[None] = (rest_netto, rest_steuer)
    return ergebnis


def _beleg_abfrage(db: Session):
    return db.query(Invoice).options(selectinload(Invoice.items))


def _belege(db: Session, von: date, bis_ausschliesslich: date | None) -> list[Invoice]:
    return _beleg_abfrage(db).filter(
        *beleg_bedingungen(UMSATZ_BELEGARTEN, von, bis_ausschliesslich),
    ).all()


def _gutschriften(db: Session, von: date, bis_ausschliesslich: date | None) -> list[Invoice]:
    original, bedingungen = gutschrift_bedingungen(
        von, topf=UMSATZ_BELEGARTEN, bis_ausschliesslich=bis_ausschliesslich,
    )
    return (
        _beleg_abfrage(db)
        .outerjoin(original, Invoice.original_invoice_id == original.id)
        .filter(*bedingungen)
        .all()
    )


def steuerkategorie_aufstellung(
    db: Session, von: date, bis_ausschliesslich: date | None = None,
) -> list[Steuerzeile]:
    """Zeilen je (Kategorie, Satz, Waehrung) im halboffenen Zeitraum
    [von, bis_ausschliesslich), netto nach Gutschriften.

    Sortiert nach Waehrung (EUR zuerst), Kategorie und Satz absteigend.
    """
    summen: dict[tuple, list[Decimal]] = defaultdict(lambda: [_NULL, _NULL])
    for vorzeichen, belege in (
        (1, _belege(db, von, bis_ausschliesslich)),
        (-1, _gutschriften(db, von, bis_ausschliesslich)),
    ):
        for beleg in belege:
            for satz, (netto, steuer) in _anteile(beleg).items():
                zeile = summen[(beleg.currency, beleg.tax_category, satz)]
                zeile[0] += vorzeichen * netto
                zeile[1] += vorzeichen * steuer
    zeilen = [
        Steuerzeile(kategorie, satz, waehrung,
                    netto.quantize(_CENT, rounding=ROUND_HALF_UP),
                    steuer.quantize(_CENT, rounding=ROUND_HALF_UP))
        for (waehrung, kategorie, satz), (netto, steuer) in summen.items()
    ]
    return sorted(zeilen, key=lambda z: (
        z.waehrung != "EUR", z.waehrung, z.kategorie,
        -(z.satz if z.satz is not None else Decimal("-1")),
    ))
