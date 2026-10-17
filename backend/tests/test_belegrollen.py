"""Rollenbesetzung je Belegart: wer ist Verkäufer (BG-4), wer Erwerber (BG-7).

Reiner Einheitentest ohne Datenbank. Die Entscheidung, die hier geprüft wird,
darf im ganzen Programm NUR in belegrollen fallen (Spec #156, „Der Schnitt"):
XML-Generator und PDF fragen dieselbe Stelle. Deshalb prüft dieser Test die
Besetzung selbst und nicht ihre Auswirkungen auf XML oder PDF.
"""
import dataclasses

import pytest
from types import SimpleNamespace

from app.services.belegart import UnknownInvoiceTypeError
from app.services.belegrollen import besetzung


def _firma():
    return SimpleNamespace(
        name="Musterfirma GmbH",
        address_line1="Firmenweg 5",
        address_line2="Gebäude Nord",
        zip_code="01234",
        city="Musterstadt",
        country="DE",
        email="buero@example.de",
        contact_name="Erika Beispiel",
        phone="+49 30 000000",
        tax_number="123/456/78901",
        vat_id="DE123456789",
    )


def _kunde():
    return SimpleNamespace(
        name="Probe Kunde AG",
        address_line1="Kundenstraße 99",
        address_line2="Hinterhof",
        zip_code="98765",
        city="Beispielheim",
        country="AT",
        email="kunde@example.org",
        customer_number="K-389",
        tax_number="98/765/43210",
        vat_id="ATU98765432",
    )


def _beleg(art):
    return SimpleNamespace(invoice_type=art)


class TestBesetzungJeBelegart:
    @pytest.mark.parametrize("art", [None, "standard", "prepayment",
                                    "credit_note", "correction"])
    def test_firma_ist_verkaeufer(self, art):
        """380, 386, 381, 384 und jede Aliasform davon bleiben wie heute."""
        rollen = besetzung(_beleg(art), _firma(), _kunde())
        assert rollen.verkaeufer_ist_firma is True
        assert rollen.verkaeufer.name == "Musterfirma GmbH"
        assert rollen.verkaeufer.steuernummer == "123/456/78901"
        assert rollen.verkaeufer.ust_id == "DE123456789"
        assert rollen.erwerber.name == "Probe Kunde AG"
        assert rollen.erwerber.kennung == "K-389"

    @pytest.mark.parametrize("art", ["self_billing", "self-billing"])
    def test_bei_389_ist_der_kunde_verkaeufer(self, art):
        """§ 14 Abs. 2 UStG: der Leistungsempfänger stellt aus, der Leistende
        ist der Verkäufer (BG-4), die eigene Firma der Erwerber (BG-7)."""
        rollen = besetzung(_beleg(art), _firma(), _kunde())
        assert rollen.verkaeufer_ist_firma is False
        assert rollen.verkaeufer.name == "Probe Kunde AG"
        assert rollen.verkaeufer.address_line1 == "Kundenstraße 99"
        assert rollen.verkaeufer.zip_code == "98765"
        assert rollen.verkaeufer.city == "Beispielheim"
        assert rollen.verkaeufer.country == "AT"
        assert rollen.verkaeufer.email == "kunde@example.org"
        assert rollen.verkaeufer.steuernummer == "98/765/43210"
        assert rollen.verkaeufer.ust_id == "ATU98765432"
        assert rollen.erwerber.name == "Musterfirma GmbH"
        assert rollen.erwerber.steuernummer == "123/456/78901"

    def test_der_kunde_hat_keinen_kontaktnamen(self):
        """Es gibt kein neues Feld dafür: fehlt der Kontakt am Verkäufer,
        entfällt der Kontaktblock (BG-6 ist optional), statt dass ein
        Kontaktpunkt erfunden würde."""
        rollen = besetzung(_beleg("self_billing"), _firma(), _kunde())
        assert rollen.verkaeufer.kontakt_name is None

    def test_die_firma_behaelt_ihren_kontaktfragenden(self):
        """Wie bisher tritt bei der Firma ohne gepflegten Namen der Firmenname
        als Kontaktpunkt (BT-41) ein; der Kontaktblock darf nicht verschwinden."""
        rollen = besetzung(_beleg(None), SimpleNamespace(**{
            **vars(_firma()), "contact_name": None}), _kunde())
        assert rollen.verkaeufer.kontakt_name == "Musterfirma GmbH"

    def test_unbekannter_typ_wirft_wie_belegart(self):
        """Fail-closed über belegart(): ein unbekannter Typ bekommt keine
        Besetzung, auch nicht die bisherige."""
        with pytest.raises(UnknownInvoiceTypeError):
            besetzung(_beleg("schnitzel"), _firma(), _kunde())

    def test_ergebnis_ist_unveraenderlich(self):
        rollen = besetzung(_beleg("self_billing"), _firma(), _kunde())
        with pytest.raises(dataclasses.FrozenInstanceError):
            rollen.verkaeufer_ist_firma = True
        with pytest.raises(dataclasses.FrozenInstanceError):
            rollen.verkaeufer.name = "Umweg"

    def test_ohne_kunden_kein_absturz(self):
        """Ein Beleg ohne Kunde hat einen leeren Erwerber (bzw. bei 389 einen
        leeren Verkäufer); das Zurückweisen übernimmt der Validator (BUYER_MISSING)."""
        rollen = besetzung(_beleg(None), _firma(), None)
        assert rollen.erwerber.name == ""
        rollen_389 = besetzung(_beleg("self_billing"), _firma(), None)
        assert rollen_389.verkaeufer.name == ""
        assert rollen_389.erwerber.name == "Musterfirma GmbH"
