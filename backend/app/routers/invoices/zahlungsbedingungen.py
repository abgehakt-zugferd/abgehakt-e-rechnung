"""Zahlungsbedingungen aus dem Rechnungsformular: Eingabe, Kundenhinweis oder
Firmenvorgabe der gewaehlten Belegsprache (#248)."""
from fastapi import HTTPException

from app.models.company import Company


def _firmen_vorgabe(company: Company, sprache: str) -> str:
    """Firmenvorgabe der gewaehlten Belegsprache; en ohne Vorgabe → 400."""
    if sprache == "en":
        vorgabe = (company.payment_terms_default_en or "").strip()
        if not vorgabe:
            raise HTTPException(
                400,
                "Englische Standard-Zahlungsbedingungen fehlen in den Einstellungen. "
                "Bitte zuerst unter Einstellungen hinterlegen.",
            )
        return vorgabe
    return (company.payment_terms_default or "").strip()


def zahlungsbedingungen(form, company: Company, sprache: str,
                        kunden_hinweis: str | None = None) -> str:
    """Leeres Feld → Zahlungshinweis des Kunden, sonst Vorgabe der gewaehlten
    Sprache. Steht genau die Vorgabe der anderen Sprache im Feld, wird sie
    durch die Vorgabe der gewaehlten Sprache ersetzt (#248). Freitext bleibt.
    Englisch ohne Vorgabe: 400.

    Der Kundenhinweis (Entscheidung 4) steht VOR der Sprachvorgabe der Firma:
    er gilt fuer DIESEN Kunden, die Firmavorgabe ist der Rueckfall fuer alle.
    Am Schreibpfad folgt danach zahlungstext_beim_speichern (#231): erst
    Sprach-Tausch, dann ggf. Gutschrift-Text auf der Firmenvorgabe.
    """
    eingabe = (form.get("payment_terms") or "").strip()
    andere = "de" if sprache == "en" else "en"
    andere_vorgabe = (
        (company.payment_terms_default or "").strip()
        if andere == "de"
        else (company.payment_terms_default_en or "").strip()
    )
    if eingabe and andere_vorgabe and eingabe == andere_vorgabe:
        return _firmen_vorgabe(company, sprache)
    if eingabe:
        return eingabe
    if kunden_hinweis:
        return kunden_hinweis
    return _firmen_vorgabe(company, sprache)
