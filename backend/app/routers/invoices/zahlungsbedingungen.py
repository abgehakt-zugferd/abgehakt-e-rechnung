"""Zahlungsbedingungen aus dem Rechnungsformular (#248, #260).

Die Regel (Eingabe, Kundenhinweis, Firmenvorgabe, Sprach-Tausch) lebt im
Dienst `belegsprache.zahlungsvorgabe`; hier nur die Uebersetzung in HTTP.
"""
from fastapi import HTTPException

from app.models.company import Company
from app.services.belegsprache.zahlungsvorgabe import (
    ZahlungsvorgabeFehlt,
    zahlungstext_in_belegsprache,
)


def zahlungsbedingungen(form, company: Company, sprache: str,
                        kunden_hinweis: str | None = None) -> str:
    """Zahlungstext der Formulareingabe; fehlende englische Vorgabe → 400.

    Am Schreibpfad folgt danach zahlungstext_beim_speichern (#231): erst
    Sprach-Tausch, dann ggf. Gutschrift-Text auf der Firmenvorgabe.
    """
    try:
        return zahlungstext_in_belegsprache(
            form.get("payment_terms"), company, sprache, kunden_hinweis,
        )
    except ZahlungsvorgabeFehlt as fehler:
        raise HTTPException(400, str(fehler)) from fehler
