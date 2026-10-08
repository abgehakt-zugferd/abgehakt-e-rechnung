"""Kennzahlen nach Storno per Gutschrift (Issue #141, docs/specs/kennzahlen-storno.md).

Grundsatz: eine Stornierung wirkt in jeder Kennzahl genau einmal. Wirksam ist eine
Gutschrift (381) mit Status issued oder paid; sie spiegelt ihr Original vollstaendig.
Die Belege entstehen hier so, wie die Anwendung sie erzeugt: mit Bezug und vollem Betrag.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services.dashboard_kennzahlen import offene_forderungen, ueberfaellige_forderungen

HEUTE = date(2026, 10, 8)


def _beleg(pg_session, *, status="issued", art=None, original=None,
           netto="100.00", steuer="19.00", ausgestellt=date(2026, 9, 1),
           faellig=date(2026, 9, 15), ersetzt=None):
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Probe Kunde",
                     address_line1="Weg 1", zip_code="80331", city="Muenchen", country="DE")
    pg_session.add(kunde)
    pg_session.flush()
    netto, steuer = Decimal(netto), Decimal(steuer)
    inv = Invoice(invoice_number=f"RE-KS-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=ausgestellt, due_date=faellig, currency="EUR",
                  net_total=netto, tax_total=steuer, gross_total=netto + steuer,
                  status=status, invoice_type=art,
                  original_invoice_id=original.id if original else None,
                  ersetzt_invoice_id=ersetzt.id if ersetzt else None,
                  bezahlt_am=ausgestellt if status == "paid" else None)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _gutschrift(pg_session, original, *, status="issued", ausgestellt=None):
    return _beleg(pg_session, status=status, art="credit_note", original=original,
                  netto=str(original.net_total), steuer=str(original.tax_total),
                  ausgestellt=ausgestellt or original.issue_date,
                  faellig=ausgestellt or original.issue_date)


def test_wirksam_stornierte_rechnung_ist_nicht_mehr_offen(pg_session):
    original = _beleg(pg_session)
    _gutschrift(pg_session, original)

    assert offene_forderungen(pg_session).betrag == Decimal("0")
    assert offene_forderungen(pg_session).anzahl == 0
    ueberfaellig = ueberfaellige_forderungen(pg_session, HEUTE)
    assert ueberfaellig.betrag == Decimal("0")
    assert ueberfaellig.aeltester_tage is None


def test_gutschrift_entwurf_oder_stornierte_gutschrift_wirkt_nicht(pg_session):
    entwurf = _beleg(pg_session)
    _gutschrift(pg_session, entwurf, status="draft")
    aufgehoben = _beleg(pg_session)
    _gutschrift(pg_session, aufgehoben, status="cancelled")

    assert offene_forderungen(pg_session).betrag == Decimal("238.00")
    from app.services.dashboard_kennzahlen import schuldige_umsatzsteuer
    assert schuldige_umsatzsteuer(pg_session, date(2026, 1, 1)) == Decimal("38.00")


JAHRESBEGINN = date(2026, 1, 1)


def test_original_zusaetzlich_von_hand_storniert_zaehlt_nur_einmal(pg_session):
    """Status und Gutschrift sind zwei Wege zur selben Aufhebung; sie addieren sich nicht."""
    from app.services.dashboard_kennzahlen import nettoumsatz_ytd, schuldige_umsatzsteuer

    original = _beleg(pg_session, status="cancelled")
    _gutschrift(pg_session, original)

    assert nettoumsatz_ytd(pg_session, JAHRESBEGINN) == Decimal("0.00")
    assert schuldige_umsatzsteuer(pg_session, JAHRESBEGINN) == Decimal("0.00")


def test_von_hand_storniert_ohne_gutschrift_zaehlt_wie_bisher_nicht(pg_session):
    from app.services.dashboard_kennzahlen import nettoumsatz_ytd

    _beleg(pg_session, status="cancelled")

    assert nettoumsatz_ytd(pg_session, JAHRESBEGINN) == Decimal("0.00")


def test_gutschrift_zu_anzahlungsrechnung_mindert_den_umsatz_nicht(pg_session):
    """Die 386 zaehlt nirgends; ihre Gutschrift darf deshalb auch nichts abziehen."""
    from app.services.dashboard_kennzahlen import nettoumsatz_ytd, schuldige_umsatzsteuer

    anzahlung = _beleg(pg_session, art="prepayment")
    _gutschrift(pg_session, anzahlung)

    assert nettoumsatz_ytd(pg_session, JAHRESBEGINN) == Decimal("0.00")
    assert schuldige_umsatzsteuer(pg_session, JAHRESBEGINN) == Decimal("0.00")


def test_gutschrift_zu_honorargutschrift_mindert_die_vorsteuer_nicht_die_ust(pg_session):
    """Die 389 steht auf der Vorsteuerseite; ihr Storno gehoert dorthin."""
    from app.services.dashboard_kennzahlen import (
        schuldige_umsatzsteuer, vorsteuer_honorargutschriften,
    )

    honorar = _beleg(pg_session, art="self_billing")
    _gutschrift(pg_session, honorar)

    assert vorsteuer_honorargutschriften(pg_session, JAHRESBEGINN) == Decimal("0.00")
    assert schuldige_umsatzsteuer(pg_session, JAHRESBEGINN) == Decimal("0.00")


def test_ausgezahlte_gutschrift_wirkt_wie_gestellte(pg_session):
    original = _beleg(pg_session)
    _gutschrift(pg_session, original, status="paid")

    assert offene_forderungen(pg_session).betrag == Decimal("0")


def test_ist_umsatz_sinkt_erst_mit_der_auszahlung_der_gutschrift(pg_session):
    """Gestellt heisst: das Geld ist noch da. Ausgezahlt heisst: es ist zurueck."""
    from app.services.dashboard_kennzahlen import umsatz_im_zeitraum

    original = _beleg(pg_session, status="paid")
    gutschrift = _gutschrift(pg_session, original, ausgestellt=date(2026, 9, 20))
    assert umsatz_im_zeitraum(pg_session, JAHRESBEGINN) == Decimal("100.00")

    gutschrift.status = "paid"
    gutschrift.bezahlt_am = date(2026, 9, 25)
    pg_session.commit()

    assert umsatz_im_zeitraum(pg_session, JAHRESBEGINN) == Decimal("0.00")


def test_gutschrift_zaehlt_im_quartal_ihrer_ausstellung(pg_session):
    from app.services.dashboard_kennzahlen import schuldige_umsatzsteuer

    original = _beleg(pg_session, ausgestellt=date(2026, 9, 1))
    _gutschrift(pg_session, original, ausgestellt=date(2026, 10, 5))

    assert schuldige_umsatzsteuer(pg_session, date(2026, 7, 1), date(2026, 9, 30)) == Decimal("19.00")
    assert schuldige_umsatzsteuer(pg_session, date(2026, 10, 1)) == Decimal("-19.00")


def _auszahlen(pg_session, gutschrift, am):
    gutschrift.status = "paid"
    gutschrift.bezahlt_am = am
    pg_session.commit()


def test_ist_umsatz_zaehlt_die_rueckzahlung_im_monat_der_auszahlung(pg_session):
    """Nach bezahlt_am der Gutschrift, nicht nach ihrem Ausstellungsdatum."""
    from app.services.dashboard_kennzahlen import umsatz_im_zeitraum

    original = _beleg(pg_session, status="paid", ausgestellt=date(2026, 3, 1))
    gutschrift = _gutschrift(pg_session, original, ausgestellt=date(2026, 3, 10))
    _auszahlen(pg_session, gutschrift, date(2026, 4, 2))

    assert umsatz_im_zeitraum(pg_session, date(2026, 1, 1), date(2026, 3, 31)) == Decimal("100.00")
    assert umsatz_im_zeitraum(pg_session, date(2026, 4, 1)) == Decimal("-100.00")


def test_ausgezahlte_gutschrift_zu_unbezahlter_rechnung_mindert_den_ist_umsatz_nicht(pg_session):
    """Ohne Zahlungseingang gibt es nichts zurueckzuzahlen."""
    from app.services.dashboard_kennzahlen import umsatz_im_zeitraum

    original = _beleg(pg_session)
    gutschrift = _gutschrift(pg_session, original)
    _auszahlen(pg_session, gutschrift, date(2026, 9, 5))

    assert umsatz_im_zeitraum(pg_session, JAHRESBEGINN) == Decimal("0.00")
    assert offene_forderungen(pg_session).betrag == Decimal("0")


def test_ersatzrechnung_zaehlt_allein_als_offene_forderung(pg_session):
    """Das Beispiel aus #141: Original, Gutschrift und Ersatzrechnung (#140).

    Erwartet 119,00 offen, nicht 238,00; Nettoumsatz 100,00, nicht 200,00 und nicht 0,00.
    """
    from app.services.dashboard_kennzahlen import nettoumsatz_ytd

    original = _beleg(pg_session)
    _gutschrift(pg_session, original)
    _beleg(pg_session, ausgestellt=date(2026, 9, 3), faellig=date(2026, 9, 17), ersetzt=original)

    offen = offene_forderungen(pg_session)
    assert (offen.anzahl, offen.betrag) == (1, Decimal("119.00"))
    assert nettoumsatz_ytd(pg_session, JAHRESBEGINN) == Decimal("100.00")
