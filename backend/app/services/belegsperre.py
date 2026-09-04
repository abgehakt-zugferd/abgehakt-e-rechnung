"""Was am Entwurf aus einem Beleg feststeht (abgehakt#22, Punkt 5).

Die Grenze verlaeuft nicht zwischen "wichtig" und "unwichtig", sondern zwischen
zwei Autoritaeten:

* Steuersatz, Steuerkategorie, Bezeichnungen und Freitexte gehoeren abgehakt.
  Der Auftrag traegt sie gar nicht; sie entstehen hier aus dem Status des
  Kunden, und eine falsche Ableitung muss man korrigieren koennen.
* Netto-Betraege, der Beteiligte und der Leistungszeitraum stammen aus dem
  signierten Beleg. Wer sie aendert, hat eine Rechnung, die auf einen Beleg
  zeigt, den sie nicht mehr wiedergibt.

Ist ein Netto-Betrag falsch, ist der BELEG falsch. Dann wird er abgelehnt und
der Absender erzeugt einen neuen; die Rechnung wird nicht zurechtgebogen. Das
ist der Unterschied zwischen einem Entwurf und einem Vorschlag.

Die Sperre steht hier und wirkt im Server. `readonly` im Formular ist eine
Bitte an den Browser und keine Zusage.
"""

from decimal import Decimal
from typing import Optional

GESPERRTE_FELDER = (
    "Beteiligter",
    "Leistungszeitraum",
    "Netto-Beträge der Positionen",
)


class BelegsperreVerletzt(ValueError):
    """Der Aufbau des Belegs laesst sich nicht aendern, nur seine Darstellung."""


def gilt(invoice) -> bool:
    """Stammt diese Rechnung aus einem signierten Uebergabebeleg?"""
    return bool(getattr(invoice, "uebergabe_beleg_sha256", None))


def positionen_binden(invoice, rohe_positionen: list) -> list:
    """Nimmt die Betraege aus dem Bestand, den Rest aus dem Formular.

    Nicht pruefen und ablehnen, sondern binden: eine Zusage, die davon abhaengt,
    dass der Browser mitspielt, ist keine. Nur die ANZAHL kann nicht gebunden
    werden - eine Position mehr oder weniger ist kein Beleg mehr.
    """
    gespeichert = sorted(invoice.items, key=lambda p: p.position)
    if len(rohe_positionen) != len(gespeichert):
        raise BelegsperreVerletzt(
            f"Dieser Entwurf stammt aus einem Beleg mit {len(gespeichert)} "
            f"Position(en); ihre Zahl ist nicht änderbar."
        )
    gebunden = []
    for eingabe, alt in zip(rohe_positionen, gespeichert):
        neu = dict(eingabe)
        neu["quantity"] = str(alt.quantity)
        neu["unit_price"] = str(alt.unit_price)
        neu["unit"] = alt.unit
        gebunden.append(neu)
    return gebunden


def betrag_unveraendert(invoice, netto: Decimal) -> bool:
    """Nachprobe fuer den Aufrufer: die Summe darf sich nicht bewegt haben."""
    return Decimal(str(invoice.net_total)) == Decimal(str(netto))
