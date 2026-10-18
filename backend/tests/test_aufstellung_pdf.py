"""Das sichtbare PDF der Abrechnungsaufstellung (§ 8b, Bauschritt 7c).

Die Aufstellung ist KEINE Rechnung: kein Rechnungstitel, kein Steuerhinweis,
kein Zahlungsblock — dafuer der abgrenzende Satz nach § 14 UStG, der
Leistungsmonat, die Zahlung des Auszahlers und die Anlagen als Nachweis.
Die Matrix de/EUR gegen en/Fremdwaehrung deckt die Beschriftungen aus
belegsprache.py ab; die Schriftpruefung ist die PDF/A-Pflicht.
"""
from datetime import date
from decimal import Decimal

from app.models.company import Company
from app.services.aufstellung_pdf import erzeuge_pdf
from tests.factories import orm_customer
from tests.factories_aufstellung import orm_anlage, orm_aufstellung
from tests.helpers.pdf import schrift_ist_eingebettet, schrift_objekte, text


def _firma():
    """Echte Struktur, keine echten Namen (Muster wie test_pdfa._company)."""
    return Company(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", email="info@example.de",
        phone="+49 111", vat_id="DE123456789", tax_number="123/456/78901",
        country="DE",
    )


def _aufstellung(*, sprache=None, **over):
    """Aufstellung mit gesetztem Ausstellungsdatum und beiden Anlagen.

    Das PDF entsteht beim Finalisieren, nachdem das Datum gesetzt ist;
    ohne Datum (Entwurf vor dem Stellen) entfaellt nur die Kopfzeile.
    """
    kw = dict(
        ausstellungsdatum=date(2026, 10, 18),
        anlagen=[
            orm_anlage("abrechnungsbericht"),
            orm_anlage("zahlungsbericht", sha256="b" * 64, groesse=4096),
        ],
    )
    kw.update(over)
    if sprache is not None:
        kw["customer"] = orm_customer(belegsprache_vorgabe=sprache)
    return orm_aufstellung(**kw)


def test_de_eur_traegt_alle_angaben(tmp_path):
    ziel = tmp_path / "aufstellung.pdf"
    erzeuge_pdf(_aufstellung(), _firma(), ziel)

    t = text(ziel)
    assert "ABRECHNUNGSAUFSTELLUNG" in t
    assert "Aufstellungsnummer:" in t
    assert "Ausstellungsdatum:" in t and "18.10.2026" in t
    assert "Leistungsmonat:" in t and "09/2026" in t
    assert "Zahlungsnummer:" in t and "4711" in t
    assert "Zahlungsdatum:" in t and "30.09.2026" in t
    assert "Aussteller" in t and "Muster Handwerk GmbH" in t
    assert "Auszahler" in t and "Kunde GmbH" in t
    assert "Brutto" in t and "1.000,00 €" in t
    assert "Quellensteuer" in t and "80,00 €" in t
    assert "Nettobetrag" in t and "920,00 €" in t
    assert "Anlagen" in t
    assert "Abrechnungsbericht" in t and "abrechnungsbericht.xlsx" in t
    assert "Zahlungsbericht" in t and "zahlungsbericht.xlsx" in t
    assert "2048" in t and "4096" in t
    assert "a" * 64 in t and "b" * 64 in t
    assert "Keine Rechnung im Sinne des § 14 UStG." in t
    assert "Seite 1 von 1" in t


def test_en_fremdwaehrung_traegt_alle_angaben(tmp_path):
    a = _aufstellung(
        sprache="en", waehrung="USD",
        kurs=Decimal("1.0843"), zahlbetrag_eur=Decimal("848.53"),
    )
    ziel = tmp_path / "statement.pdf"
    erzeuge_pdf(a, _firma(), ziel)

    t = text(ziel)
    assert "SETTLEMENT STATEMENT" in t
    assert "Statement number:" in t
    assert "Date of issue:" in t and "2026-10-18" in t
    assert "Month of service:" in t and "09/2026" in t
    assert "Payment number:" in t and "4711" in t
    assert "Payment date:" in t and "2026-09-30" in t
    assert "Issuer" in t and "Muster Handwerk GmbH" in t
    assert "Payer" in t and "Kunde GmbH" in t
    assert "Gross" in t and "USD 1,000.00" in t
    assert "Withholding tax" in t and "USD 80.00" in t
    assert "Net amount" in t and "USD 920.00" in t
    assert "Exchange rate" in t and "1.0843" in t
    assert "Payment amount" in t and "EUR 848.53" in t
    assert "Settlement report" in t and "Payment report" in t
    assert (
        "Not an invoice within the meaning of section 14 of the German VAT Act."
        in t
    )
    assert "Page 1 of 1" in t


def test_de_fremdwaehrung_druckt_kurs_und_zahlbetrag(tmp_path):
    """Festlegung 21: Abgehakt rechnet nichts um — gedruckt wird der Kurs
    mit den Stellen, die gespeichert sind, und der Zahlbetrag, wie er
    im Auftrag stand."""
    a = _aufstellung(
        waehrung="USD", kurs=Decimal("1.0843"), zahlbetrag_eur=Decimal("848.53"),
    )
    ziel = tmp_path / "aufstellung.pdf"
    erzeuge_pdf(a, _firma(), ziel)

    t = text(ziel)
    assert "Kurs" in t and "1,0843" in t
    assert "Zahlbetrag" in t and "848,53 €" in t


def test_eur_hat_keine_kurszeile(tmp_path):
    """Bei Berichtswaehrung EUR gibt es nichts umzurechnen (DB-CHECK):
    eine Kurszeile waere eine Angabe, die niemand geprueft hat."""
    ziel = tmp_path / "aufstellung.pdf"
    erzeuge_pdf(_aufstellung(), _firma(), ziel)

    t = text(ziel)
    assert "Kurs" not in t
    assert "Zahlbetrag" not in t


def test_alle_schriften_eingebettet(tmp_path):
    """PDF/A-Pflicht: keine Helvetica aus Canvas-Praembel oder Tabellenzelle
    (docs/DEV-DOCU.md, 'PDF/A-Schriften einbetten')."""
    ziel = tmp_path / "aufstellung.pdf"
    erzeuge_pdf(_aufstellung(), _firma(), ziel)

    objekte = list(schrift_objekte(ziel))
    assert objekte, "PDF enthält keine Font-Ressourcen"
    for fo in objekte:
        basis = str(fo.get("/BaseFont", ""))
        assert schrift_ist_eingebettet(fo), f"Font nicht eingebettet: {basis}"
        assert "Helvetica" not in basis and "Times" not in basis and "Courier" not in basis, \
            f"Standard-14-Font verblieben: {basis}"


def test_fuss_zeigt_pflichtangaben_der_firma(tmp_path):
    ziel = tmp_path / "aufstellung.pdf"
    erzeuge_pdf(_aufstellung(), _firma(), ziel)

    t = text(ziel)
    assert "Muster Handwerk GmbH" in t
    assert "Steuernummer: 123/456/78901" in t
    assert "USt-IdNr.: DE123456789" in t
