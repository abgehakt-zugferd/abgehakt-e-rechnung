"""Der Auftragsschluessel des vorgelagerten Systems an einem Beleg
(Bauschritt 4a, Entscheidung 7 und Festlegung 12 aus
docs/specs/rechnungs-und-aufstellungsauftrag.md; Bauschritt 7a erweitert
ihn auf die Abrechnungsaufstellung).

Zwei Spalten, eine Stelle: `auftragsschluessel` ist der Nachweis, aus welchem
Auftrag der Beleg entstand, und bleibt nach dem Finalisieren unveraenderlich
(invoice_guard, aufstellung_guard). `auftragsschluessel_offen` traegt
denselben Wert, solange der Beleg sperrt, und NULL, sobald er freigibt —
beim Verwerfen, beim Finalisieren der Stornorechnung zum Original, beim
manuellen Stornieren und beim Storno der Aufstellung. Der Status taugt
nicht als Kriterium: Eine per Stornorechnung aufgehobene Rechnung bleibt
'issued' oder 'paid', deshalb sperrt die eigene Spalte mit ihrem
partiellen Unique-Index, und der Index sichert die Zusage gegen zwei
gleichzeitige Anfragen — je Tabelle.

Kein Aufrufer schreibt die Spalten direkt: Belegen, Freigeben und die Frage,
ob zu einem Schluessel bereits ein Beleg besteht, gehen durch dieses Modul —
sonst muessten die Regeln an jeder Aufrufstelle einzeln erinnert werden und
wuerden auseinanderlaufen.

Warum kein gemeinsamer Index ueber beide Tabellen: Ein Unique-Index in
Postgres lebt auf GENAU EINER Tabelle; „dieser Schluessel ist in invoices
oder aufstellungen nur einmal offen" liesse sich nur mit einem DB-Trigger
oder einer dritten Tabelle erzwingen. Beides waere eine zweite Maschine
neben der Statuslogik der Guards. Die Zusicherung lebt deshalb HIER, an der
einen Stelle, die beide Tabellen sieht: belegen prueft die JEWEILS ANDERE
Tabelle, dokument_zu liest beide. Konflikte innerhalb EINER Tabelle sind
bewusst nicht Sache von belegen — dafuer gibt es den partiellen Unique-Index
und die Vorabpruefung der Routen (Festlegung 19), und der Index schlaegt beim
Commit mit derselben Meldung zu, die auch die Route sagt; wuerde belegen
vorziehen, naeme es den Routen ihre zweite Schicht (400 statt 500). Ein
transienter Beleg (noch ohne Session, etwa frisch aus der Fabrik) kann hier
nicht geprueft werden — sein Aufrufer fragt dokument_zu, bevor er committet.
"""
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.models.aufstellung import Aufstellung
from app.models.invoice import Invoice


class SchluesselBelegtError(RuntimeError):
    """Der Schluessel sperrt bereits einen Beleg der jeweils anderen Art.
    Dafuer gibt es keinen Index (siehe Modul-Doku), deshalb wirft die eine
    Stelle, die beide Tabellen sieht."""


def belegen(beleg, schluessel: str) -> None:
    """Setzt Nachweis und Sperre, nachdem die ANDERE Tabelle geprueft ist.

    Erneut gerufen wird er beim Zurueckholen eines verworfenen Entwurfs: Der
    Nachweis steht dann schon (er bleibt unveraendert), nur die Sperre
    kommt zurueck. Die eigene Tabelle prueft er nicht: Deren Wettlauf
    schlaegt der partielle Unique-Index beim Commit, und die Routen melden
    ihn wie ihre Vorabpruefung (Festlegung 19).
    """
    db = object_session(beleg)
    if db is not None:
        andere = Invoice if isinstance(beleg, Aufstellung) else Aufstellung
        if db.execute(
            select(andere.id).where(andere.auftragsschluessel_offen == schluessel)
        ).first() is not None:
            raise SchluesselBelegtError(
                "Dieser Auftragsschluessel sperrt bereits einen Beleg der "
                "jeweils anderen Art (Rechnung oder Abrechnungsaufstellung)."
            )
    beleg.auftragsschluessel = schluessel
    beleg.auftragsschluessel_offen = schluessel


def freigeben(beleg) -> None:
    """Hebt nur die Sperre auf; der Nachweis bleibt fuer die Akte. Nach dem
    Finalisieren ist das Leeren der einzige erlaubte Eingriff in die Spalte
    (invoice_guard, aufstellung_guard)."""
    beleg.auftragsschluessel_offen = None


def dokument_zu(db: Session, schluessel: str) -> Optional[str]:
    """Nummer des Belegs, der diesen Schluessel derzeit sperrt — 'Entwurf',
    wenn er noch nicht gestellt ist —, oder None, wenn der Schluessel frei ist.

    § 8a und § 8b: genannt wird, was der Absender wiedererkennt, und das
    Format spricht von „einem Dokument" (Festlegung 12): Rechnung wie
    Abrechnungsaufstellung gehoeren in die Antwort.
    """
    rechnung = db.execute(
        select(Invoice).where(Invoice.auftragsschluessel_offen == schluessel)
    ).scalar_one_or_none()
    if rechnung is not None:
        return "Entwurf" if rechnung.status == "draft" else rechnung.invoice_number

    aufstellung = db.execute(
        select(Aufstellung).where(Aufstellung.auftragsschluessel_offen == schluessel)
    ).scalar_one_or_none()
    if aufstellung is not None:
        return "Entwurf" if aufstellung.status == "draft" else aufstellung.nummer
    return None
