"""Wie Rechnungsstatus in der Oberfläche gelesen werden.

`issued` bedeutet finalisiert (GoBD-Beleg steht), nicht zugestellt. Ob die Mail
rausging, steht in `datev_sent_at` (Erstversand an Kunde, DATEV im BCC). Ohne
diese Trennung sieht eine versendete Rechnung wie eine offene Forderung.
"""
from datetime import datetime

_ETIKETT = {
    "draft": "Entwurf",
    "paid": "Bezahlt",
    "cancelled": "Storniert",
    "discarded": "Verworfen",
}


def ist_nicht_versendet(status: str, datev_sent_at: datetime | None = None) -> bool:
    """Finalisiert, aber ohne Erstversand — eine Bedingung fuer Etikett und Kennzahl."""
    return status == "issued" and datev_sent_at is None


def etikett(status: str, datev_sent_at: datetime | None = None) -> str:
    if status == "issued":
        return "Nicht versendet" if ist_nicht_versendet(status, datev_sent_at) else "Versendet"
    return _ETIKETT.get(status, status)


def badge_klasse(status: str, datev_sent_at: datetime | None = None) -> str:
    if status == "issued":
        return "offen" if ist_nicht_versendet(status, datev_sent_at) else "sent"
    return status
