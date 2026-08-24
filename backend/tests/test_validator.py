"""Tests für die regelbasierte Rechnungsvalidierung (§ 14 UStG + EN16931 Business Rules).

Abgedeckte Regeln:
  BR-2  (Rechnungsnummer), BR-3 (Ausstellungsdatum), BR-10 (Verkäufername),
  BR-15 (Käufername), BR-21 (Fälligkeitsdatum ≥ Ausstellungsdatum),
  BR-22 (Menge > 0), BR-25 (Zeilenbetrag = Menge × Preis),
  BR-26 (Nettopreis ≥ 0), BR-54 (MwSt.-Kategorie-Code),
  BR-64/65 (Summenkorrektheit),
  § 14 Abs. 4 Nr. 2 UStG (Steuernummer/USt-IdNr.),
  § 14 Abs. 4 Nr. 6 UStG (Leistungsdatum),
  § 14a Abs. 1 UStG (USt-IdNr. Käufer > 10.000 €),
  § 33 UStDV (Kleinbetragsregelung).
"""
import pytest
from decimal import Decimal
from datetime import date

from app.services.validator import validate_invoice, Issue
from tests.factories import (
    company_stub as _company,
    customer_stub as _customer,
    item_stub as _item,
    validator_invoice_stub as _invoice,
)


def _codes(issues: list[Issue]) -> set[str]:
    return {i.code for i in issues}


# ── Hilfsfunktion ──────────────────────────────────────────────────────────

def _validate(invoice=None, company=None):
    return validate_invoice(invoice or _invoice(), company or _company())


# ── Tests: Happy Path ──────────────────────────────────────────────────────

def test_valid_invoice_no_errors():
    """Vollständige Rechnung produziert keine Fehler."""
    errors, warnings = _validate()
    assert errors == []


def test_valid_invoice_may_have_warnings_but_no_errors():
    """Auch mit Warnungen darf es keine Fehler geben."""
    inv = _invoice(payment_terms=None)  # erzeugt Warning NO_PAYMENT_TERMS
    errors, _ = validate_invoice(inv, _company())
    assert errors == []


# ── Tests: Pflichtfelder Verkäufer ─────────────────────────────────────────

def test_seller_name_missing():
    """BR-10: Fehlender Firmenaname → SELLER_NAME_MISSING."""
    errors, _ = validate_invoice(_invoice(), _company(name=""))
    assert "SELLER_NAME_MISSING" in _codes(errors)


def test_seller_name_whitespace_only():
    """Name nur aus Leerzeichen → ebenfalls Fehler."""
    errors, _ = validate_invoice(_invoice(), _company(name="   "))
    assert "SELLER_NAME_MISSING" in _codes(errors)


def test_seller_address_incomplete_no_zip():
    """Fehlende PLZ → SELLER_ADDRESS_MISSING."""
    errors, _ = validate_invoice(_invoice(), _company(zip_code=""))
    assert "SELLER_ADDRESS_MISSING" in _codes(errors)


def test_seller_address_incomplete_no_city():
    """Fehlende Stadt → SELLER_ADDRESS_MISSING."""
    errors, _ = validate_invoice(_invoice(), _company(city=""))
    assert "SELLER_ADDRESS_MISSING" in _codes(errors)


def test_seller_no_tax_id_at_all():
    """§ 14 Abs. 4 Nr. 2 UStG: Weder Steuernummer noch USt-IdNr. → SELLER_TAX_ID_MISSING."""
    errors, _ = validate_invoice(_invoice(), _company(tax_number=None, vat_id=None))
    assert "SELLER_TAX_ID_MISSING" in _codes(errors)


def test_seller_vat_id_alone_is_sufficient():
    """Nur USt-IdNr. genügt – kein SELLER_TAX_ID_MISSING."""
    errors, _ = validate_invoice(_invoice(), _company(tax_number=None, vat_id="DE123456789"))
    assert "SELLER_TAX_ID_MISSING" not in _codes(errors)


def test_seller_tax_number_alone_is_sufficient():
    """Nur Steuernummer genügt – kein SELLER_TAX_ID_MISSING."""
    errors, _ = validate_invoice(_invoice(), _company(tax_number="12/345/67890", vat_id=None))
    assert "SELLER_TAX_ID_MISSING" not in _codes(errors)


# ── Tests: Pflichtfelder Käufer ────────────────────────────────────────────

def test_no_customer_assigned():
    """Fehlender Kunde → BUYER_MISSING."""
    errors, _ = validate_invoice(_invoice(customer=None), _company())
    assert "BUYER_MISSING" in _codes(errors)


def test_buyer_name_missing():
    """BR-15: Leerer Kundename → BUYER_NAME_MISSING."""
    errors, _ = validate_invoice(_invoice(customer=_customer(name="")), _company())
    assert "BUYER_NAME_MISSING" in _codes(errors)


def test_buyer_address_incomplete():
    """Fehlende Käuferadresse → BUYER_ADDRESS_MISSING."""
    errors, _ = validate_invoice(_invoice(customer=_customer(address_line1="")), _company())
    assert "BUYER_ADDRESS_MISSING" in _codes(errors)


def test_high_value_b2b_no_buyer_vat_id_is_warning_not_error():
    """Betrag > 10.000 € ohne USt-IdNr. Käufer → HIGH_VALUE_NO_BUYER_VAT_ID (WARNING, kein ERROR).

    Fachlich korrekt: § 14a Abs. 1 UStG verlangt die USt-IdNr. des Empfängers nur bei
    Leistungen i.S.d. § 3a Abs. 2 UStG (grenzüberschreitend/Reverse Charge), NICHT generell
    bei inländischen B2B-Rechnungen über 10.000 €. Die 10.000-€-Schwelle stammt aus dem
    österreichischen UStG (§ 11 Abs. 1 Z 2), nicht aus deutschem Recht. Eine inländische
    Rechnung über 10.000 € an einen Kunden ohne USt-IdNr. ist zulässig und darf daher nicht
    hart blockiert werden – ein Hinweis (Warning) ist angemessen.
    """
    big_item = _item(quantity=Decimal("100.0000"), unit_price=Decimal("100.00"),
                     net_amount=Decimal("10000.00"), tax_amount=Decimal("1900.00"),
                     gross_amount=Decimal("11900.00"))
    inv = _invoice(items=[big_item],
                   net_total=Decimal("10000.00"), tax_total=Decimal("1900.00"),
                   gross_total=Decimal("11900.00"),
                   customer=_customer(vat_id=None))
    errors, warnings = validate_invoice(inv, _company())
    # Warnung wird gesetzt, aber NICHT als Fehler
    assert "HIGH_VALUE_NO_BUYER_VAT_ID" in _codes(warnings)
    assert "HIGH_VALUE_NO_BUYER_VAT_ID" not in _codes(errors)
    # Der alte (falsche) Error-Code darf nicht mehr auftauchen
    assert "BUYER_VAT_ID_REQUIRED_HIGH_VALUE" not in _codes(errors)
    # Die Rechnung bleibt finalisierbar: keine Fehler nur wegen des hohen Betrags
    assert errors == []


def test_high_value_with_buyer_vat_id_no_warning():
    """> 10.000 € MIT USt-IdNr. → kein HIGH_VALUE_NO_BUYER_VAT_ID Warning."""
    inv = _invoice(gross_total=Decimal("15000.00"),
                   customer=_customer(vat_id="DE987654321"))
    errors, warnings = validate_invoice(inv, _company())
    assert "HIGH_VALUE_NO_BUYER_VAT_ID" not in _codes(warnings)
    assert "HIGH_VALUE_NO_BUYER_VAT_ID" not in _codes(errors)


def test_exactly_10000_no_warning():
    """Genau 10.000 € → kein Warning (Grenze ist >10.000 €)."""
    inv = _invoice(gross_total=Decimal("10000.00"), customer=_customer(vat_id=None))
    _, warnings = validate_invoice(inv, _company())
    assert "HIGH_VALUE_NO_BUYER_VAT_ID" not in _codes(warnings)


# ── Tests: Rechnungsdaten ──────────────────────────────────────────────────

def test_invoice_number_missing():
    """BR-2: Fehlende Rechnungsnummer → INVOICE_NUMBER_MISSING."""
    errors, _ = validate_invoice(_invoice(invoice_number=""), _company())
    assert "INVOICE_NUMBER_MISSING" in _codes(errors)


def test_invoice_number_none():
    errors, _ = validate_invoice(_invoice(invoice_number=None), _company())
    assert "INVOICE_NUMBER_MISSING" in _codes(errors)


def test_issue_date_missing():
    """BR-3: Fehlendes Ausstellungsdatum → ISSUE_DATE_MISSING."""
    errors, _ = validate_invoice(_invoice(issue_date=None), _company())
    assert "ISSUE_DATE_MISSING" in _codes(errors)


def test_due_date_before_issue_date():
    """BR-21: Fälligkeitsdatum vor Ausstellungsdatum → DUE_DATE_BEFORE_ISSUE."""
    inv = _invoice(issue_date=date(2026, 6, 11), due_date=date(2026, 6, 10))
    errors, _ = validate_invoice(inv, _company())
    assert "DUE_DATE_BEFORE_ISSUE" in _codes(errors)


def test_due_date_same_as_issue_date_is_valid():
    """Fälligkeitsdatum = Ausstellungsdatum ist erlaubt."""
    inv = _invoice(issue_date=date(2026, 6, 11), due_date=date(2026, 6, 11))
    errors, _ = validate_invoice(inv, _company())
    assert "DUE_DATE_BEFORE_ISSUE" not in _codes(errors)


# ── Tests: Leistungsdatum ──────────────────────────────────────────────────

def test_delivery_date_missing_is_error_for_non_simplified():
    """#98 E7 (Produktentscheid 2026-07-23: harter Gate): Fehlendes Leistungsdatum bei
    einer Rechnung ≥ 250 € (nicht Kleinbetrag) ist ein harter Fehler (§ 14 Abs. 4 Nr. 6
    UStG verlangt den Leistungszeitpunkt zwingend) — blockiert die Finalisierung, nicht
    mehr nur eine Warnung."""
    # qty=1, price=250 → net=250, tax=47.50, gross=297.50 (> 250 € Schwelle)
    item = _item(quantity=Decimal("1.0000"), unit_price=Decimal("250.00"),
                 net_amount=Decimal("250.00"), tax_amount=Decimal("47.50"),
                 gross_amount=Decimal("297.50"))
    inv = _invoice(items=[item], delivery_date=None,
                   net_total=Decimal("250.00"), tax_total=Decimal("47.50"),
                   gross_total=Decimal("297.50"))
    errors, warnings = validate_invoice(inv, _company())
    assert "DELIVERY_DATE_MISSING" in _codes(errors)
    assert "DELIVERY_DATE_MISSING" not in _codes(warnings)


def test_delivery_date_missing_ok_for_simplified():
    """§ 33 UStDV: Unter 250 € (Kleinbetragsrechnung) → kein DELIVERY_DATE_MISSING,
    weder Fehler noch Warnung."""
    inv = _invoice(delivery_date=None, gross_total=Decimal("249.99"))
    errors, warnings = validate_invoice(inv, _company())
    assert "DELIVERY_DATE_MISSING" not in _codes(errors)
    assert "DELIVERY_DATE_MISSING" not in _codes(warnings)


@pytest.mark.parametrize("brutto,pflicht", [
    (Decimal("249.99"), False),
    (Decimal("250.00"), False),   # die Grenze selbst gehört noch zum Kleinbetrag
    (Decimal("250.01"), True),    # der erste Cent darüber
])
def test_kleinbetragsgrenze_liegt_bei_genau_250_euro(brutto, pflicht):
    """§ 33 UStDV: „deren Gesamtbetrag 250 Euro nicht übersteigt".

    Nicht übersteigen heißt bis einschließlich. Bei genau 250,00 € brutto verlangte
    die Prüfung bisher trotzdem ein Leistungsdatum und wies die Finalisierung ab —
    für eine Rechnung, die das Gesetz ausdrücklich davon befreit. Die drei Werte
    stehen zusammen, weil erst der Cent darüber beweist, dass die Grenze noch
    irgendwo liegt.
    """
    inv = _invoice(delivery_date=None, gross_total=brutto)

    errors, warnings = validate_invoice(inv, _company())

    assert ("DELIVERY_DATE_MISSING" in _codes(errors)) is pflicht
    assert "DELIVERY_DATE_MISSING" not in _codes(warnings)


def test_delivery_date_set_no_warning():
    """Leistungsdatum gesetzt → kein DELIVERY_DATE_MISSING auch über 250 €."""
    inv = _invoice(delivery_date=date(2026, 6, 10), gross_total=Decimal("500.00"))
    _, warnings = validate_invoice(inv, _company())
    assert "DELIVERY_DATE_MISSING" not in _codes(warnings)


def _ig_lieferung(**over):
    """Innergemeinschaftliche Lieferung unter der Kleinbetragsgrenze.

    Bis auf das, was der einzelne Test wegnimmt, vollständig gültig: 0 % Steuer
    (sonst TAX_CATEGORY_RATE_MISMATCH) und USt-IdNr. des Käufers (sonst
    BUYER_VAT_ID_REQUIRED). Ohne beides wäre ein Fehlerfall-Test grün, ohne dass
    das Leistungsdatum je geprüft worden wäre.
    """
    item = _item(quantity=Decimal("1.0000"), unit_price=Decimal("200.00"),
                 tax_rate=Decimal("0.00"), net_amount=Decimal("200.00"),
                 tax_amount=Decimal("0.00"), gross_amount=Decimal("200.00"))
    kw = dict(tax_category="K", items=[item],
              net_total=Decimal("200.00"), tax_total=Decimal("0.00"),
              gross_total=Decimal("200.00"),
              customer=_customer(country="AT", city="Wien", vat_id="ATU12345678"))
    kw.update(over)
    return _invoice(**kw)


def test_ig_lieferung_verlangt_das_leistungsdatum_auch_beim_kleinbetrag():
    """#47: EN16931 BR-IC-11 verlangt bei innergemeinschaftlicher Lieferung das
    Lieferdatum (BT-72) oder einen Abrechnungszeitraum, unabhängig vom Betrag.

    § 33 UStDV erlässt nur die nationale Pflichtangabe; die europäische Norm gilt
    daneben weiter. Ohne diese Regel kam der Beleg am Gate vorbei und scheiterte
    danach an Mustang, mit einer Meldung, die niemandem sagt, was zu tun ist. Der
    Beweis dafür steht als Schema-Test in test_zugferd_xml_schema.py.
    """
    errors, warnings = validate_invoice(_ig_lieferung(delivery_date=None), _company())

    assert "DELIVERY_DATE_MISSING" in _codes(errors)
    assert "DELIVERY_DATE_MISSING" not in _codes(warnings)


def test_ig_lieferung_mit_leistungsdatum_ist_fehlerfrei():
    """Gutfall: sonst wäre die Regel ununterscheidbar von „K geht nie durch"."""
    errors, _ = validate_invoice(_ig_lieferung(), _company())

    assert errors == [], [f.code for f in errors]


def test_die_meldung_zur_ig_lieferung_nennt_ihren_eigenen_grund():
    """Die Standardmeldung nennt die 250-€-Grenze. Hier stünde sie im Widerspruch
    zum Formular, das bis 250 € einschließlich Freiwilligkeit zusagt, und ließe den
    Nutzer glauben, er habe sich verrechnet."""
    errors, _ = validate_invoice(_ig_lieferung(delivery_date=None), _company())
    meldung = next(f.message for f in errors if f.code == "DELIVERY_DATE_MISSING")

    assert "250" not in meldung, meldung
    assert "innergemeinschaftlich" in meldung.lower(), meldung


@pytest.mark.parametrize("kategorie", ["S", "AE", "O", "E"])
def test_nur_die_ig_lieferung_durchbricht_die_kleinbetragsgrenze(kategorie):
    """Die Ausnahme gilt K allein, nicht allen steuerfreien Kategorien.

    Gegen das echte Mustang geprüft: ohne Leistungsdatum bleiben S, AE, O und E
    gültig, nur K fällt über BR-IC-11. Eine breitere Regel würde Rechnungen
    blockieren, die die Norm annimmt.
    """
    inv = _ig_lieferung(delivery_date=None, tax_category=kategorie,
                        customer=_customer(vat_id="ATU12345678"))

    errors, warnings = validate_invoice(inv, _company())

    assert "DELIVERY_DATE_MISSING" not in _codes(errors)
    assert "DELIVERY_DATE_MISSING" not in _codes(warnings)


def test_ig_lieferung_nennt_ihren_grund_auch_ueber_250_euro():
    """Über der Grenze verlangen beide Seiten dasselbe Datum, § 14 Abs. 4 Nr. 6
    UStG und BR-IC-11. Die Meldung nennt dann durchgehend den engeren Grund, damit
    sie nicht davon abhängt, ob der Betrag gerade über oder unter 250 € liegt."""
    item = _item(quantity=Decimal("1.0000"), unit_price=Decimal("300.00"),
                 tax_rate=Decimal("0.00"), net_amount=Decimal("300.00"),
                 tax_amount=Decimal("0.00"), gross_amount=Decimal("300.00"))
    inv = _ig_lieferung(delivery_date=None, items=[item],
                        net_total=Decimal("300.00"), tax_total=Decimal("0.00"),
                        gross_total=Decimal("300.00"))

    errors, _ = validate_invoice(inv, _company())
    meldung = next(f.message for f in errors if f.code == "DELIVERY_DATE_MISSING")

    assert "innergemeinschaftlich" in meldung.lower(), meldung


# ── Tests: Rechnungspositionen ─────────────────────────────────────────────

def test_no_items():
    """Keine Positionen → NO_ITEMS."""
    errors, _ = validate_invoice(_invoice(items=[]), _company())
    assert "NO_ITEMS" in _codes(errors)


def test_item_description_missing():
    """§ 14 Abs. 4 Nr. 5 UStG: Fehlende Leistungsbeschreibung → ITEM_DESCRIPTION_MISSING."""
    errors, _ = validate_invoice(_invoice(items=[_item(description="")]), _company())
    assert "ITEM_DESCRIPTION_MISSING" in _codes(errors)


def test_item_quantity_zero():
    """BR-22: Menge 0 → ITEM_QUANTITY_INVALID."""
    errors, _ = validate_invoice(_invoice(items=[_item(quantity=Decimal("0"))]), _company())
    assert "ITEM_QUANTITY_INVALID" in _codes(errors)


def test_item_quantity_negative():
    """BR-22: Negative Menge → ITEM_QUANTITY_INVALID."""
    errors, _ = validate_invoice(_invoice(items=[_item(quantity=Decimal("-1"))]), _company())
    assert "ITEM_QUANTITY_INVALID" in _codes(errors)


def test_item_unit_price_negative():
    """BR-26: Negativer Einzelpreis → ITEM_PRICE_NEGATIVE."""
    errors, _ = validate_invoice(_invoice(items=[_item(unit_price=Decimal("-10.00"))]), _company())
    assert "ITEM_PRICE_NEGATIVE" in _codes(errors)


def test_item_unit_price_zero_is_valid():
    """Einzelpreis 0 ist erlaubt (Gratisposition)."""
    item = _item(unit_price=Decimal("0.00"), net_amount=Decimal("0.00"),
                 tax_amount=Decimal("0.00"), gross_amount=Decimal("0.00"))
    inv = _invoice(items=[item], net_total=Decimal("0.00"),
                   tax_total=Decimal("0.00"), gross_total=Decimal("0.00"))
    errors, _ = validate_invoice(inv, _company())
    assert "ITEM_PRICE_NEGATIVE" not in _codes(errors)


def test_item_invalid_tax_rate():
    """BR-54: Ungültiger Steuersatz (z.B. 15%) → TAX_RATE_INVALID."""
    item = _item(tax_rate=Decimal("15.00"))
    errors, _ = validate_invoice(_invoice(items=[item]), _company())
    assert "TAX_RATE_INVALID" in _codes(errors)


def test_item_nonstandard_integer_rates_rejected():
    """Auch plausibel wirkende, aber in DE ungültige GANZZAHLIGE Sätze müssen fallen.
    16% (COVID-Satz 2020), 20% (AT-Satz), 5%, 8% sind keine deutschen Sätze (nur 0/7/19).
    Regressionsschutz gegen versehentliches Aufweichen von VALID_TAX_RATES.
    """
    for bad_rate in [Decimal("5"), Decimal("8"), Decimal("16"), Decimal("20")]:
        item = _item(tax_rate=bad_rate)
        errors, _ = validate_invoice(_invoice(items=[item]), _company())
        assert "TAX_RATE_INVALID" in _codes(errors), f"Steuersatz {bad_rate}% muss ungültig sein"


def test_item_valid_tax_rates_0_7_19():
    """Steuersätze 0%, 7%, 19% sind alle gültig."""
    for rate in [Decimal("0"), Decimal("7"), Decimal("19")]:
        item = _item(tax_rate=rate, tax_amount=(Decimal("200.00") * rate / 100).quantize(Decimal("0.01")))
        net = Decimal("200.00")
        tax = (net * rate / 100).quantize(Decimal("0.01"))
        gross = net + tax
        item_with_amounts = _item(tax_rate=rate, net_amount=net, tax_amount=tax, gross_amount=gross)
        inv = _invoice(items=[item_with_amounts], net_total=net, tax_total=tax, gross_total=gross)
        errors, _ = validate_invoice(inv, _company())
        assert "TAX_RATE_INVALID" not in _codes(errors), f"Steuersatz {rate}% sollte gültig sein"


def test_item_amount_mismatch():
    """BR-25: Nettobetrag stimmt nicht mit Menge × Preis überein → ITEM_AMOUNT_MISMATCH."""
    # Menge 2, Preis 100 → erwartet 200, aber 195 angegeben
    item = _item(quantity=Decimal("2.0000"), unit_price=Decimal("100.00"),
                 net_amount=Decimal("195.00"), tax_amount=Decimal("37.05"),
                 gross_amount=Decimal("232.05"))
    errors, _ = validate_invoice(_invoice(items=[item]), _company())
    assert "ITEM_AMOUNT_MISMATCH" in _codes(errors)


def test_item_tax_mismatch():
    """BR-65: Steuerbetrag stimmt nicht mit Nettobetrag × Steuersatz → ITEM_TAX_MISMATCH."""
    # Net 200, 19% → erwartet 38, aber 35 angegeben
    item = _item(net_amount=Decimal("200.00"), tax_rate=Decimal("19.00"),
                 tax_amount=Decimal("35.00"), gross_amount=Decimal("235.00"))
    errors, _ = validate_invoice(_invoice(items=[item]), _company())
    assert "ITEM_TAX_MISMATCH" in _codes(errors)


def test_item_amount_within_tolerance():
    """Rundungsfehler ≤ 0,02 € werden toleriert."""
    # Menge × Preis = 3.3333 × 10.00 = 33.33 (gerundet), net_amount = 33.33
    item = _item(quantity=Decimal("3.3333"), unit_price=Decimal("10.00"),
                 net_amount=Decimal("33.33"), tax_amount=Decimal("6.33"),
                 gross_amount=Decimal("39.66"))
    inv = _invoice(items=[item], net_total=Decimal("33.33"),
                   tax_total=Decimal("6.33"), gross_total=Decimal("39.66"))
    errors, _ = validate_invoice(inv, _company())
    assert "ITEM_AMOUNT_MISMATCH" not in _codes(errors)


# ── Tests: Gesamtbeträge ───────────────────────────────────────────────────

def test_net_total_mismatch():
    """BR-64: Nettosumme stimmt nicht → NET_TOTAL_MISMATCH."""
    item = _item(net_amount=Decimal("200.00"))
    inv = _invoice(items=[item], net_total=Decimal("150.00"),  # falsch
                   tax_total=Decimal("38.00"), gross_total=Decimal("238.00"))
    errors, _ = validate_invoice(inv, _company())
    assert "NET_TOTAL_MISMATCH" in _codes(errors)


def test_tax_total_mismatch():
    """Steuersumme stimmt nicht → TAX_TOTAL_MISMATCH."""
    item = _item(tax_amount=Decimal("38.00"))
    inv = _invoice(items=[item], net_total=Decimal("200.00"),
                   tax_total=Decimal("30.00"),  # falsch
                   gross_total=Decimal("238.00"))
    errors, _ = validate_invoice(inv, _company())
    assert "TAX_TOTAL_MISMATCH" in _codes(errors)


def test_gross_total_mismatch():
    """Bruttosumme stimmt nicht → GROSS_TOTAL_MISMATCH."""
    inv = _invoice(net_total=Decimal("200.00"),
                   tax_total=Decimal("38.00"),
                   gross_total=Decimal("999.00"))  # falsch
    errors, _ = validate_invoice(inv, _company())
    assert "GROSS_TOTAL_MISMATCH" in _codes(errors)


def test_totals_correct_no_mismatch_errors():
    """Korrekte Beträge → keine Mismatch-Fehler."""
    errors, _ = _validate()
    mismatch_codes = {"NET_TOTAL_MISMATCH", "TAX_TOTAL_MISMATCH", "GROSS_TOTAL_MISMATCH",
                      "ITEM_AMOUNT_MISMATCH", "ITEM_TAX_MISMATCH"}
    assert not mismatch_codes & _codes(errors)


# ── Tests: Empfehlungen (Warnings) ────────────────────────────────────────

def test_missing_payment_terms_warning():
    """Fehlende Zahlungsbedingungen → NO_PAYMENT_TERMS (Warning, kein Fehler)."""
    inv = _invoice(payment_terms=None)
    errors, warnings = validate_invoice(inv, _company())
    assert errors == []
    assert "NO_PAYMENT_TERMS" in _codes(warnings)


def test_missing_bank_iban_warning():
    """Fehlende Bankverbindung → NO_BANK_DETAILS (Warning)."""
    _, warnings = validate_invoice(_invoice(), _company(bank_iban=None))
    assert "NO_BANK_DETAILS" in _codes(warnings)


def test_bank_iban_set_no_warning():
    """IBAN hinterlegt → kein NO_BANK_DETAILS."""
    _, warnings = validate_invoice(_invoice(), _company(bank_iban="DE89370400440532013000"))
    assert "NO_BANK_DETAILS" not in _codes(warnings)


# ── Tests: Mehrere Fehler gleichzeitig ────────────────────────────────────

def test_multiple_errors_returned_together():
    """Mehrere Fehler werden alle gesammelt, nicht nur der erste."""
    inv = _invoice(invoice_number=None, issue_date=None, customer=None, items=[])
    errors, _ = validate_invoice(inv, _company(name="", tax_number=None, vat_id=None))
    error_codes = _codes(errors)
    assert "SELLER_NAME_MISSING" in error_codes
    assert "SELLER_TAX_ID_MISSING" in error_codes
    assert "INVOICE_NUMBER_MISSING" in error_codes
    assert "ISSUE_DATE_MISSING" in error_codes
    assert "BUYER_MISSING" in error_codes
    assert "NO_ITEMS" in error_codes


def test_issue_object_fields():
    """Issue-Objekte haben korrekte Felder: code, severity, message, field."""
    errors, _ = validate_invoice(_invoice(invoice_number=None), _company())
    issue = next(i for i in errors if i.code == "INVOICE_NUMBER_MISSING")
    assert issue.severity == "error"
    assert issue.message
    assert issue.field == "invoice_number"


# ── MwSt.-Kategorien ───────────────────────────────────────────────────────

class TestTaxCategory:

    def test_tax_category_invalid_code(self):
        inv = _invoice(tax_category="X")
        errors, _ = validate_invoice(inv, _company())
        assert "TAX_CATEGORY_INVALID" in _codes(errors)

    def test_tax_category_g_is_out_of_scope(self):
        """Bewusste Scope-Grenze (2026-07-08): 'G' (Ausfuhr Drittland) ist nicht
        umgesetzt und muss als ungültig fallen. Locking-Test: verhindert stilles
        Aufnehmen ohne Fachentscheid.

        'E' stand bis zum 09.08.2026 ebenfalls hier. Der Fachentscheid dazu ist
        mit #152 gefallen: 'E' meint jetzt genau den Kleinunternehmer nach § 19
        UStG, mit passendem Befreiungsgrund. Der Test hat also getan, wofür er da
        war — er hat die Aufnahme so lange verhindert, bis jemand hinsah.
        """
        inv = _invoice(tax_category="G")
        errors, _ = validate_invoice(inv, _company())
        assert "TAX_CATEGORY_INVALID" in _codes(errors), \
            "Kategorie G ist außerhalb des Scope und muss ungültig sein"

    def test_tax_category_ae_with_nonzero_rate_raises_error(self):
        item = _item(tax_rate=Decimal("19.00"), net_amount=Decimal("200.00"),
                     tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))
        inv = _invoice(
            tax_category="AE",
            items=[item],
            net_total=Decimal("200.00"),
            tax_total=Decimal("38.00"),
            gross_total=Decimal("238.00"),
        )
        errors, _ = validate_invoice(inv, _company())
        assert "TAX_CATEGORY_RATE_MISMATCH" in _codes(errors)

    def test_tax_category_k_with_nonzero_rate_raises_error(self):
        item = _item(tax_rate=Decimal("7.00"), net_amount=Decimal("200.00"),
                     tax_amount=Decimal("14.00"), gross_amount=Decimal("214.00"))
        inv = _invoice(
            tax_category="K",
            items=[item],
            net_total=Decimal("200.00"),
            tax_total=Decimal("14.00"),
            gross_total=Decimal("214.00"),
        )
        errors, _ = validate_invoice(inv, _company())
        assert "TAX_CATEGORY_RATE_MISMATCH" in _codes(errors)

    def test_tax_category_o_with_nonzero_rate_raises_error(self):
        item = _item(tax_rate=Decimal("19.00"), net_amount=Decimal("200.00"),
                     tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))
        inv = _invoice(
            tax_category="O",
            items=[item],
            net_total=Decimal("200.00"),
            tax_total=Decimal("38.00"),
            gross_total=Decimal("238.00"),
        )
        errors, _ = validate_invoice(inv, _company())
        assert "TAX_CATEGORY_RATE_MISMATCH" in _codes(errors)

    def test_tax_category_ae_without_buyer_vat_id_raises_error(self):
        item = _item(tax_rate=Decimal("0.00"), net_amount=Decimal("200.00"),
                     tax_amount=Decimal("0.00"), gross_amount=Decimal("200.00"))
        inv = _invoice(
            tax_category="AE",
            items=[item],
            net_total=Decimal("200.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("200.00"),
            customer=_customer(vat_id=None),
        )
        errors, _ = validate_invoice(inv, _company())
        assert "BUYER_VAT_ID_REQUIRED" in _codes(errors)

    def test_tax_category_k_without_buyer_vat_id_raises_error(self):
        item = _item(tax_rate=Decimal("0.00"), net_amount=Decimal("200.00"),
                     tax_amount=Decimal("0.00"), gross_amount=Decimal("200.00"))
        inv = _invoice(
            tax_category="K",
            items=[item],
            net_total=Decimal("200.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("200.00"),
            customer=_customer(vat_id=None),
        )
        errors, _ = validate_invoice(inv, _company())
        assert "BUYER_VAT_ID_REQUIRED" in _codes(errors)

    def test_tax_category_o_does_not_require_buyer_vat_id(self):
        item = _item(tax_rate=Decimal("0.00"), net_amount=Decimal("200.00"),
                     tax_amount=Decimal("0.00"), gross_amount=Decimal("200.00"))
        inv = _invoice(
            tax_category="O",
            items=[item],
            net_total=Decimal("200.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("200.00"),
            customer=_customer(vat_id=None),
        )
        errors, _ = validate_invoice(inv, _company())
        assert "BUYER_VAT_ID_REQUIRED" not in _codes(errors)

    def test_tax_category_ae_valid_no_errors(self):
        item = _item(tax_rate=Decimal("0.00"), net_amount=Decimal("200.00"),
                     tax_amount=Decimal("0.00"), gross_amount=Decimal("200.00"))
        inv = _invoice(
            tax_category="AE",
            items=[item],
            net_total=Decimal("200.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("200.00"),
            customer=_customer(vat_id="FI12345678"),
        )
        errors, _ = validate_invoice(inv, _company())
        assert "TAX_CATEGORY_RATE_MISMATCH" not in _codes(errors)
        assert "BUYER_VAT_ID_REQUIRED" not in _codes(errors)
        assert "TAX_CATEGORY_INVALID" not in _codes(errors)

    def test_tax_category_e_valid_no_errors(self):
        """#31: E (Kleinunternehmer § 19) muss in der zentralen Validator-Suite
        positiv abgedeckt sein, nicht nur in test_kleinunternehmer.py."""
        item = _item(tax_rate=Decimal("0.00"), net_amount=Decimal("500.00"),
                     tax_amount=Decimal("0.00"), gross_amount=Decimal("500.00"))
        inv = _invoice(
            tax_category="E",
            items=[item],
            net_total=Decimal("500.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("500.00"),
        )
        errors, _ = validate_invoice(inv, _company())
        assert "TAX_CATEGORY_RATE_MISMATCH" not in _codes(errors)
        assert "TAX_CATEGORY_INVALID" not in _codes(errors)

    def test_inland_zero_rate_does_not_trigger_rate_mismatch(self):
        item = _item(tax_rate=Decimal("0.00"), net_amount=Decimal("200.00"),
                     tax_amount=Decimal("0.00"), gross_amount=Decimal("200.00"))
        inv = _invoice(
            tax_category="S",
            items=[item],
            net_total=Decimal("200.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("200.00"),
        )
        errors, _ = validate_invoice(inv, _company())
        assert "TAX_CATEGORY_RATE_MISMATCH" not in _codes(errors)

    def test_steuerkategorie_o_verlangt_steuer_nummer(self):
        """#46: nur USt-IdNr. reicht bei Kategorie O nicht — sonst Sackgasse bei Mustang."""
        item = _item(tax_rate=Decimal("0.00"), net_amount=Decimal("200.00"),
                     tax_amount=Decimal("0.00"), gross_amount=Decimal("200.00"))
        inv = _invoice(
            tax_category="O",
            items=[item],
            net_total=Decimal("200.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("200.00"),
        )
        errors, _ = validate_invoice(inv, _company(tax_number=None, vat_id="DE123456789"))
        assert "SELLER_TAX_NUMBER_REQUIRED_FOR_O" in _codes(errors)


# ── Konsistenz invoice_type ↔ original_invoice_id (ROADMAP Punkt 3) ──────────
import uuid


def test_unknown_invoice_type_is_error():
    errors, _ = _validate(_invoice(invoice_type="stornorechnung"))  # Tippfehler statt 'storno'
    assert "INVOICE_TYPE_INVALID" in _codes(errors)


def test_credit_note_without_original_is_error():
    errors, _ = _validate(_invoice(invoice_type="credit_note", original_invoice_id=None))
    assert "ORIGINAL_INVOICE_REQUIRED" in _codes(errors)


def test_credit_note_with_original_is_ok():
    errors, _ = _validate(_invoice(invoice_type="credit_note", original_invoice_id=uuid.uuid4()))
    assert "ORIGINAL_INVOICE_REQUIRED" not in _codes(errors)
    assert "INVOICE_TYPE_INVALID" not in _codes(errors)


def test_standard_invoice_with_original_is_error():
    errors, _ = _validate(_invoice(invoice_type=None, original_invoice_id=uuid.uuid4()))
    assert "ORIGINAL_INVOICE_NOT_ALLOWED" in _codes(errors)


def test_standard_invoice_without_original_is_clean():
    errors, _ = _validate(_invoice())
    assert "ORIGINAL_INVOICE_NOT_ALLOWED" not in _codes(errors)
    assert "INVOICE_TYPE_INVALID" not in _codes(errors)
    assert "ORIGINAL_INVOICE_REQUIRED" not in _codes(errors)


# ── ZUGFeRD-Profil: MINIMUM/BASIC-WL sind nicht rechtskonform (#98 E4) ────────

def test_profile_minimum_is_error():
    """MINIMUM ist keine gültige E-Rechnung (§ 14 UStG verlangt mind. EN16931) →
    harter Fehler, blockiert die Finalisierung."""
    errors, _ = _validate(_invoice(zugferd_profile="MINIMUM"))
    assert "PROFILE_NOT_COMPLIANT" in _codes(errors)


def test_profile_basic_wl_is_error():
    """BASIC-WL (ohne Positionen) ist ebenfalls nicht rechtskonform."""
    errors, _ = _validate(_invoice(zugferd_profile="BASIC-WL"))
    assert "PROFILE_NOT_COMPLIANT" in _codes(errors)


def test_profile_en16931_no_error():
    """EN16931 (Default) ist konform — kein Profil-Fehler."""
    errors, _ = _validate(_invoice(zugferd_profile="EN16931"))
    assert "PROFILE_NOT_COMPLIANT" not in _codes(errors)
