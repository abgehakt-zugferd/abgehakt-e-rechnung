"""PDF folgt derselben Rollenbesetzung wie die XML (Spec #156, Umfang 2).

Kopf (Absender-/Empfängerangaben, Kundennummer, USt-IdNr. des Erwerbers) und
Seitenfuß (Steuerkennung des Verkäufers) lesen dieselbe Quelle wie der
XML-Generator: belegrollen. 380 läuft als Regression mit umgekehrter Erwartung.
"""
import re

from pypdf import PdfReader

from app.services import pdf_generator
from tests.factories import company_stub, customer_stub, validator_invoice_stub


def _firma():
    return company_stub(
        name="Musterfirma GmbH",
        address_line1="Firmenweg 5",
        address_line2="Gebäude Nord",
        zip_code="01234",
        city="Musterstadt",
        country="DE",
        email="buero@example.de",
        phone="+49 30 000000",
        contact_name="Erika Beispiel",
        tax_number="123/456/78901",
        vat_id="DE123456789",
    )


def _kunde(**over):
    return customer_stub(
        name="Probe Kunde AG",
        address_line1="Kundenstraße 99",
        address_line2="Hinterhof",
        zip_code="98765",
        city="Beispielheim",
        country="DE",
        email="kunde@example.org",
        customer_number="K-389",
        tax_number="98/765/43210",
        vat_id="DE987654321",
        **over,
    )


def _beleg(art, kunde):
    return validator_invoice_stub(
        invoice_type=art,
        customer=kunde,
        payment_terms="14 Tage netto",
        notes=None,
    )


def _pdf_text(inv, company, tmp_path):
    out = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, company, out)
    return "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)


class TestFussSteuerkennung:
    def test_389_fuss_zeigt_die_steuerkennung_des_leistenden(self, tmp_path):
        """Bei 389 steht im Fuß die Kennung des Verkäufers, und das ist der
        Kunde; die eigene Firma steht dort nicht."""
        text = _pdf_text(_beleg("self_billing", _kunde()), _firma(), tmp_path)
        assert "Steuernummer 98/765/43210" in text
        assert "USt-IdNr. DE987654321" in text
        assert "123/456/78901" not in text
        assert "DE123456789" not in text

    def test_380_fuss_zeigt_weiterhin_die_eigene_steuerkennung(self, tmp_path):
        text = _pdf_text(_beleg(None, _kunde()), _firma(), tmp_path)
        assert "Steuernummer 123/456/78901" in text
        assert "USt-IdNr. DE123456789" in text
        assert "98/765/43210" not in text


class TestKopfAbsenderUndEmpfaenger:
    def test_389_kopf_fuehrt_den_kunden_als_absender(self, tmp_path):
        """Die Absenderangabe im Kopf ist die des Verkäufers (BG-4), hier also
        die des Kunden. Die Empfängerangabe nennt die eigene Firma."""
        text = _pdf_text(_beleg("self_billing", _kunde()), _firma(), tmp_path)
        assert re.search(r"Probe Kunde AG\s*·\s*Kundenstraße 99", text), (
            "Die Absenderzeile folgt nicht der Rollenbesetzung."
        )
        # Absenderangabe (Kopf rechts) und Absenderzeile tragen den Verkäufer,
        # die Empfängeranschrift den Erwerber: die Firmenadresse steht genau
        # einmal (Empfänger), die Kundenadresse zweimal.
        assert text.count("98765") == 2
        assert text.count("01234") == 1

    def test_380_kopf_fuehrt_die_firma_als_absender(self, tmp_path):
        text = _pdf_text(_beleg(None, _kunde()), _firma(), tmp_path)
        assert re.search(r"Musterfirma GmbH\s*·\s*Firmenweg 5", text), (
            "Die Absenderzeile folgt nicht der Rollenbesetzung."
        )
        assert text.count("01234") == 2
        assert text.count("98765") == 1


class TestKopfKundenkennung:
    def test_389_nennt_keine_kundennummer_der_eigenen_firma(self, tmp_path):
        """Erwerber ist die eigene Firma; sie hat keine Kundennummer, also
        entfällt die Zeile statt leer zu bleiben."""
        text = _pdf_text(_beleg("self_billing", _kunde()), _firma(), tmp_path)
        assert "Kundennummer:" not in text

    def test_380_nennt_die_kundennummer_des_erwerbers(self, tmp_path):
        text = _pdf_text(_beleg(None, _kunde()), _firma(), tmp_path)
        assert "Kundennummer: K-389" in text

    def test_389_nennt_die_ust_id_des_erwerbers(self, tmp_path):
        """Die Zeile „USt-IdNr. Kunde" nennt den Erwerber, wie BT-50 in der XML."""
        text = _pdf_text(_beleg("self_billing", _kunde()), _firma(), tmp_path)
        assert "USt-IdNr. Kunde: DE123456789" in text

    def test_380_nennt_die_ust_id_des_kunden(self, tmp_path):
        text = _pdf_text(_beleg(None, _kunde()), _firma(), tmp_path)
        assert "USt-IdNr. Kunde: DE987654321" in text
