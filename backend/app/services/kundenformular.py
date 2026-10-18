"""Gemeinsame Formularlogik fuer Anlegen und Bearbeiten eines Kunden."""

from __future__ import annotations

from app.models.customer import Customer
from app.services import empfaenger
from app.services.adresse import bereinige_adresszeile2
from app.services.bankverbindung import normalisiere_bic, normalisiere_iban, pruefe_bic, pruefe_iban
from app.services.steuerstatus import (
    UST_STATUS_UNGEKLAERT,
    steuerfelder_uebernehmen,
    ust_status_aus_formular,
)

# Wertevorraete der Kundenvorgaben (Festlegung 13): Formular und DB-CHECK
# (Migration 025) pruefen denselben Vorrat. Ausserhalb des Vorrats ist ein
# manipulierter POST, kein Tippfehler — die Auswahl bietet nur diese Werte.
AUFTRAG_STEUER_WERTE = frozenset({"AE"})
BELEGSPRACHE_VORGABEN = frozenset({"de", "en"})


def vorgaben_pruefen(auftrag_steuer: str, belegsprache_vorgabe: str) -> str | None:
    """Prueft die beiden Vorgaben mit Wertevorrat; None heisst in Ordnung.

    Der DB-CHECK allein wuerde aus einem manipulierten POST einen 500er machen;
    hier wird derselbe Vorrat vorher als Formularfehler gemeldet.
    """
    steuer = (auftrag_steuer or "").strip()
    if steuer and steuer not in AUFTRAG_STEUER_WERTE:
        return f"Unbekannte Steuervorgabe: {steuer}"
    sprache = (belegsprache_vorgabe or "").strip()
    if sprache and sprache not in BELEGSPRACHE_VORGABEN:
        return f"Unbekannte Belegsprachenvorgabe: {sprache}"
    return None


def vorgaben_speichern(
    customer: Customer,
    *,
    auftrag_steuer: str,
    kopftext: str,
    fusstext: str,
    zahlungshinweis: str,
    belegsprache_vorgabe: str,
) -> None:
    customer.auftrag_steuer = (auftrag_steuer or "").strip() or None
    customer.kopftext = kopftext.strip() or None
    customer.fusstext = fusstext.strip() or None
    customer.zahlungshinweis = zahlungshinweis.strip() or None
    customer.belegsprache_vorgabe = (belegsprache_vorgabe or "").strip() or None


def bank_felder(bank_iban: str, bank_bic: str, bank_name: str) -> tuple[dict, str | None]:
    """Normalisiert Bankfelder oder liefert Formularwerte + Fehlermeldung."""
    roh = {
        "bank_iban": bank_iban,
        "bank_bic": bank_bic,
        "bank_name": bank_name,
    }
    iban_fehler = pruefe_iban(bank_iban)
    if iban_fehler:
        return roh, iban_fehler
    bic_fehler = pruefe_bic(bank_bic)
    if bic_fehler:
        return roh, bic_fehler
    return {
        "bank_iban": bank_iban,
        "bank_bic": bank_bic,
        "bank_name": bank_name.strip(),
    }, None


def bank_speichern(customer: Customer, felder: dict) -> None:
    customer.bank_iban = normalisiere_iban(felder.get("bank_iban"))
    customer.bank_bic = normalisiere_bic(felder.get("bank_bic"))
    customer.bank_name = (felder.get("bank_name") or "").strip() or None


def stammdaten_setzen(
    customer: Customer,
    *,
    name: str,
    address_line1: str,
    address_line2: str,
    zip_code: str,
    city: str,
    country: str,
    email: str,
    cc_emails: str,
    phone: str,
    notes: str,
    is_active: str,
) -> None:
    customer.name = name.strip()
    customer.address_line1 = address_line1.strip()
    customer.address_line2 = bereinige_adresszeile2(name, address_line2)
    customer.zip_code = zip_code.strip()
    customer.city = city.strip()
    customer.country = country.strip() or "DE"
    customer.email = email.strip() or None
    customer.cc_emails = empfaenger.normalisiere(cc_emails) or None
    customer.phone = phone.strip() or None
    customer.notes = notes.strip() or None
    customer.is_active = (is_active == "1")


def steuer_speichern(
    customer: Customer,
    *,
    ust_status: str,
    gutschriftempfaenger: str,
    tax_number: str,
) -> None:
    steuerfelder_uebernehmen(
        customer,
        ust_status_roh=ust_status,
        gutschriftempfaenger_roh=gutschriftempfaenger,
        tax_number_roh=tax_number,
    )


def formularwerte(
    *,
    number: str,
    name: str,
    address_line1: str,
    address_line2: str,
    zip_code: str,
    city: str,
    country: str,
    vat_id: str,
    tax_number: str,
    ust_status: str,
    gutschriftempfaenger: str,
    email: str,
    phone: str,
    notes: str,
    cc_emails: str,
    auftrag_steuer: str = "",
    kopftext: str = "",
    fusstext: str = "",
    zahlungshinweis: str = "",
    belegsprache_vorgabe: str = "",
) -> dict:
    return {
        "customer_number": number,
        "name": name,
        "address_line1": address_line1,
        "address_line2": address_line2,
        "zip_code": zip_code,
        "city": city,
        "country": country,
        "vat_id": vat_id,
        "tax_number": tax_number,
        "ust_status": ust_status_aus_formular(ust_status) or UST_STATUS_UNGEKLAERT,
        "gutschriftempfaenger": gutschriftempfaenger,
        "email": email,
        "phone": phone,
        "notes": notes,
        "cc_emails": cc_emails,
        "auftrag_steuer": auftrag_steuer,
        "kopftext": kopftext,
        "fusstext": fusstext,
        "zahlungshinweis": zahlungshinweis,
        "belegsprache_vorgabe": belegsprache_vorgabe,
    }
