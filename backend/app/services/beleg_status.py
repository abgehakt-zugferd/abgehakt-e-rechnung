"""Wie Rechnungsstatus in der Oberfläche gelesen werden.

`issued` bedeutet finalisiert (GoBD-Beleg steht), nicht zugestellt. Ob der
KUNDE den Beleg hat, steht in `kunde_zugestellt_am`; die Buchhaltung hat ihren
eigenen Vermerk in `datev_sent_at`. Ohne diese Trennung sieht eine Rechnung,
die nur der Buchhaltung vorliegt, wie eine erledigte aus, obwohl die Forderung
beim Kunden noch nicht einmal bekannt ist.
"""
from datetime import datetime

from sqlalchemy import and_

_ETIKETT = {
    "draft": "Entwurf",
    "paid": "Bezahlt",
    "cancelled": "Storniert",
    "discarded": "Verworfen",
}


def ist_nicht_versendet(status: str, kunde_zugestellt_am: datetime | None = None) -> bool:
    """Finalisiert, aber ohne Erstzustellung an den KUNDEN — eine Bedingung
    fuer Etikett und Kennzahl. `datev_sent_at` zaehlt hier bewusst nicht: Ein
    Beleg nur an die Buchhaltung ist keine Zustellung an den Kunden."""
    return status == "issued" and kunde_zugestellt_am is None


def nicht_versendet_bedingung(status_spalte, zustell_spalte):
    """`ist_nicht_versendet` als SQL-Ausdruck: beide Haelften der Regel, nicht eine.

    Die Spalten kommen als Parameter herein, statt dass dieses Modul `Invoice`
    importiert. Es bleibt damit frei von der Rechnung und von der Datenbank; wer
    die Etiketten liest, muss das Modell nicht kennen.

    Der Zwilling in Python steht direkt darueber. Zwei Fassungen derselben Regel
    sind unvermeidlich (ein `and`-Ausdruck ist keine SQL-Bedingung), nebeneinander
    im selben Modul faellt ihr Auseinanderlaufen aber auf.
    """
    return and_(status_spalte == "issued", zustell_spalte.is_(None))


def ohne_zustellung_bedingung(spalte):
    """SQLAlchemy-Ausdruck: keine Kundenzustellung, unabhaengig vom Status.

    NICHT dasselbe wie `ist_nicht_versendet`: ein Entwurf hat auch keine
    Kundenzustellung. Das ist die Filterdimension der Rechnungsliste und bleibt
    absichtlich rechtwinklig zum Statusfilter daneben, damit `versand=offen`
    nicht heimlich den Status mitfiltert. Wer den Belegzustand meint, nimmt
    `nicht_versendet_bedingung`.
    """
    return spalte.is_(None)


def etikett(status: str, kunde_zugestellt_am: datetime | None = None) -> str:
    if status == "issued":
        return "Nicht versendet" if ist_nicht_versendet(status, kunde_zugestellt_am) else "Versendet"
    return _ETIKETT.get(status, status)


def badge_klasse(status: str, kunde_zugestellt_am: datetime | None = None) -> str:
    if status == "issued":
        return "offen" if ist_nicht_versendet(status, kunde_zugestellt_am) else "sent"
    return status
