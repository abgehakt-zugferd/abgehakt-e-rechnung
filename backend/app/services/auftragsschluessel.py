"""Der Auftragsschluessel des vorgelagerten Systems an einem Beleg
(Bauschritt 4a, Entscheidung 7 und Festlegung 12 aus
docs/specs/rechnungs-und-aufstellungsauftrag.md).

Zwei Spalten, eine Stelle: `auftragsschluessel` ist der Nachweis, aus welchem
Auftrag der Beleg entstand, und bleibt nach dem Finalisieren unveraenderlich
(invoice_guard). `auftragsschluessel_offen` traegt denselben Wert, solange der
Beleg sperrt, und NULL, sobald er freigibt — beim Verwerfen, beim Finalisieren
der Stornorechnung zum Original und beim manuellen Stornieren. Der Status
taugt nicht als Kriterium: Eine per Stornorechnung aufgehobene Rechnung bleibt
'issued' oder 'paid', deshalb sperrt die eigene Spalte mit ihrem partiellen
Unique-Index, und der Index sichert die Zusage gegen zwei gleichzeitige
Anfragen.

Kein Aufrufer schreibt die Spalten direkt: Belegen, Freigeben und die Frage,
ob zu einem Schluessel bereits ein Beleg besteht, gehen durch dieses Modul —
sonst muessten die Regeln an jeder Aufrufstelle einzeln erinnert werden und
wuerden auseinanderlaufen.
"""
from typing import Optional

from sqlalchemy.orm import Session

from app.models.invoice import Invoice


def belegen(invoice: Invoice, schluessel: str) -> None:
    """Setzt Nachweis und Sperre. Erneut gerufen wird er beim Zurueckholen
    eines verworfenen Entwurfs: Der Nachweis steht dann schon (er bleibt
    unveraendert), nur die Sperre kommt zurueck."""
    invoice.auftragsschluessel = schluessel
    invoice.auftragsschluessel_offen = schluessel


def freigeben(invoice: Invoice) -> None:
    """Hebt nur die Sperre auf; der Nachweis bleibt fuer die Akte. Nach dem
    Finalisieren ist das Leeren der einzige erlaubte Eingriff in die Spalte
    (invoice_guard)."""
    invoice.auftragsschluessel_offen = None


def dokument_zu(db: Session, schluessel: str) -> Optional[str]:
    """Nummer des Belegs, der diesen Schluessel derzeit sperrt — 'Entwurf',
    wenn er noch nicht gestellt ist —, oder None, wenn der Schluessel frei ist.

    § 8a: genannt wird, was der Absender wiedererkennt. Die Abrechnungs-
    aufstellung gehoert ebenfalls in die Antwort, denn das Format spricht von
    'einem Dokument' (Festlegung 12); ihr Modell entsteht in Bauschritt 4b
    und wird dann hier mit abgefragt.
    """
    zeile = (
        db.query(Invoice)
        .filter(Invoice.auftragsschluessel_offen == schluessel)
        .first()
    )
    if zeile is None:
        return None
    return "Entwurf" if zeile.status == "draft" else zeile.invoice_number
