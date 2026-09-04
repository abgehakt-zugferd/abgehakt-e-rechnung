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


def etikett(status: str, datev_sent_at: datetime | None = None) -> str:
    if status == "issued":
        return "Versendet" if datev_sent_at else "Nicht versendet"
    return _ETIKETT.get(status, status)


def badge_klasse(status: str, datev_sent_at: datetime | None = None) -> str:
    if status == "issued":
        return "sent" if datev_sent_at else "offen"
    return status
