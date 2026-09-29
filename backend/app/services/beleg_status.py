"""Wie Rechnungsstatus in der Oberfläche gelesen werden.

`issued` bedeutet finalisiert (GoBD-Beleg steht), nicht zugestellt. Ob die Mail
rausging, steht in `datev_sent_at` (Erstversand an Kunde, DATEV im BCC). Ohne
diese Trennung sieht eine versendete Rechnung wie eine offene Forderung.
"""
from datetime import datetime

from sqlalchemy import and_

_ETIKETT = {
    "draft": "Entwurf",
    "paid": "Bezahlt",
    "cancelled": "Storniert",
    "discarded": "Verworfen",
}


def ist_nicht_versendet(status: str, datev_sent_at: datetime | None = None) -> bool:
    """Finalisiert, aber ohne Erstversand — eine Bedingung fuer Etikett und Kennzahl."""
    return status == "issued" and datev_sent_at is None


def nicht_versendet_bedingung(status_spalte, versand_spalte):
    """`ist_nicht_versendet` als SQL-Ausdruck: beide Haelften der Regel, nicht eine.

    Die Spalten kommen als Parameter herein, statt dass dieses Modul `Invoice`
    importiert. Es bleibt damit frei von der Rechnung und von der Datenbank; wer
    die Etiketten liest, muss das Modell nicht kennen.

    Der Zwilling in Python steht direkt darueber. Zwei Fassungen derselben Regel
    sind unvermeidlich (ein `and`-Ausdruck ist keine SQL-Bedingung), nebeneinander
    im selben Modul faellt ihr Auseinanderlaufen aber auf.
    """
    return and_(status_spalte == "issued", versand_spalte.is_(None))


def ohne_erstversand_bedingung(spalte):
    """SQLAlchemy-Ausdruck: kein Erstversand, unabhaengig vom Status.

    NICHT dasselbe wie `ist_nicht_versendet`: ein Entwurf hat auch keinen
    Erstversand. Das ist die Filterdimension der Rechnungsliste und bleibt
    absichtlich rechtwinklig zum Statusfilter daneben, damit `versand=offen`
    nicht heimlich den Status mitfiltert. Wer den Belegzustand meint, nimmt
    `nicht_versendet_bedingung`.
    """
    return spalte.is_(None)


def etikett(status: str, datev_sent_at: datetime | None = None) -> str:
    if status == "issued":
        return "Nicht versendet" if ist_nicht_versendet(status, datev_sent_at) else "Versendet"
    return _ETIKETT.get(status, status)


def badge_klasse(status: str, datev_sent_at: datetime | None = None) -> str:
    if status == "issued":
        return "offen" if ist_nicht_versendet(status, datev_sent_at) else "sent"
    return status
