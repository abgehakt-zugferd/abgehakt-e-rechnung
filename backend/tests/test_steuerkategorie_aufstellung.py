"""Aufstellung der Umsaetze je Steuerkategorie und Satz (Issue #256).

Die Aufstellung nutzt dieselbe Belegmenge und Zeitlogik wie die Kennzahlen
(`dashboard_kennzahlen`); ihre Zeilen ergeben in EUR Nettoumsatz und schuldige
Umsatzsteuer desselben Zeitraums. Belege anderer Waehrung stehen getrennt.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.invoice_nebenmodelle import InvoiceItem
from app.services.dashboard_kennzahlen import nettoumsatz_ytd, schuldige_umsatzsteuer
from app.services.steuerkategorie_aufstellung import steuerkategorie_aufstellung

VON = date(2026, 7, 1)
BIS = date(2026, 10, 1)
TAG = date(2026, 8, 15)


def _kunde(pg_session):
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Probe Kunde",
                     address_line1="Weg 1", zip_code="80331", city="Muenchen", country="DE")
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _beleg(pg_session, positionen, *, kategorie="S", status="issued", art=None,
           original=None, ausgestellt=TAG, waehrung="EUR", abzug=None,
           netto=None, steuer=None, bezahlt_am=None):
    """`positionen`: Liste (netto, satz). Kopfsummen folgen den Positionen,
    ausser `netto`/`steuer` ueberschreiben sie (Abzug, Altbestand)."""
    kunde = _kunde(pg_session)
    items = []
    for nr, (n, satz) in enumerate(positionen, start=1):
        n, satz = Decimal(n), Decimal(satz)
        st = (n * satz / 100).quantize(Decimal("0.01"))
        items.append(InvoiceItem(position=nr, description="Leistung", quantity=1,
                                 unit_price=n, tax_rate=satz, net_amount=n,
                                 tax_amount=st, gross_amount=n + st))
    n_kopf = Decimal(netto) if netto is not None else sum((i.net_amount for i in items), Decimal("0"))
    s_kopf = Decimal(steuer) if steuer is not None else sum((i.tax_amount for i in items), Decimal("0"))
    inv = Invoice(invoice_number=f"RE-SK-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=ausgestellt, due_date=ausgestellt, currency=waehrung,
                  net_total=n_kopf, tax_total=s_kopf, gross_total=n_kopf + s_kopf,
                  status=status, invoice_type=art, tax_category=kategorie,
                  abzug_betrag=Decimal(abzug) if abzug is not None else None,
                  abzug_grund="Nachlass" if abzug is not None else None,
                  original_invoice_id=original.id if original else None,
                  bezahlt_am=bezahlt_am)
    inv.items = items
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _gutschrift(pg_session, original, **kw):
    return _beleg(pg_session, [(i.net_amount, i.tax_rate) for i in original.items],
                  kategorie=original.tax_category, art="credit_note", original=original,
                  netto=original.net_total, steuer=original.tax_total,
                  abzug=original.abzug_betrag, **kw)


def _zeilen(pg_session, von=VON, bis=BIS):
    return {(z.kategorie, z.satz, z.waehrung): (z.netto, z.steuer)
            for z in steuerkategorie_aufstellung(pg_session, von, bis)}


def _eur_summen(pg_session, von=VON, bis=BIS):
    zeilen = [z for z in steuerkategorie_aufstellung(pg_session, von, bis)
              if z.waehrung == "EUR"]
    return (sum((z.netto for z in zeilen), Decimal("0")),
            sum((z.steuer for z in zeilen), Decimal("0")))


def test_nullsatz_und_reverse_charge_zaehlen_netto_zum_umsatz_ohne_steuer(pg_session):
    """Bestehende Kennzahlen: 0-%-Belege (O, AE) erhoehen Netto, nicht die USt."""
    _beleg(pg_session, [("100.00", "19")])
    vorher_netto = nettoumsatz_ytd(pg_session, VON)
    vorher_ust = schuldige_umsatzsteuer(pg_session, VON, BIS)

    _beleg(pg_session, [("200.00", "0")], kategorie="O")
    _beleg(pg_session, [("300.00", "0")], kategorie="AE")

    assert nettoumsatz_ytd(pg_session, VON) == vorher_netto + Decimal("500.00")
    assert schuldige_umsatzsteuer(pg_session, VON, BIS) == vorher_ust == Decimal("19.00")


def test_zeilen_je_kategorie_und_satz_auch_bei_gemischten_saetzen(pg_session):
    _beleg(pg_session, [("100.00", "19")])
    _beleg(pg_session, [("100.00", "19"), ("50.00", "7")])  # gemischter Beleg
    _beleg(pg_session, [("200.00", "0")], kategorie="O")
    _beleg(pg_session, [("300.00", "0")], kategorie="AE")

    assert _zeilen(pg_session) == {
        ("S", Decimal("19"), "EUR"): (Decimal("200.00"), Decimal("38.00")),
        ("S", Decimal("7"), "EUR"): (Decimal("50.00"), Decimal("3.50")),
        ("O", Decimal("0"), "EUR"): (Decimal("200.00"), Decimal("0.00")),
        ("AE", Decimal("0"), "EUR"): (Decimal("300.00"), Decimal("0.00")),
    }


def test_summe_der_zeilen_gleich_kennzahlen_mit_gutschrift(pg_session):
    standard = _beleg(pg_session, [("100.00", "19"), ("50.00", "7")])
    _beleg(pg_session, [("300.00", "0")], kategorie="AE")
    _gutschrift(pg_session, standard, ausgestellt=date(2026, 9, 1))

    netto, ust = _eur_summen(pg_session)

    assert netto == nettoumsatz_ytd(pg_session, VON) == Decimal("300.00")
    assert ust == schuldige_umsatzsteuer(pg_session, VON, BIS) == Decimal("0.00")
    assert _zeilen(pg_session)[("S", Decimal("19"), "EUR")] == (Decimal("0.00"), Decimal("0.00"))


def test_gutschrift_mindert_zeile_ihrer_kategorie(pg_session):
    _beleg(pg_session, [("100.00", "19")])
    _beleg(pg_session, [("400.00", "0")], kategorie="AE")
    ae = _beleg(pg_session, [("100.00", "0")], kategorie="AE")
    _gutschrift(pg_session, ae)

    assert _zeilen(pg_session)[("AE", Decimal("0"), "EUR")] == (Decimal("400.00"), Decimal("0.00"))


def test_belegabzug_geht_in_der_summe_auf(pg_session):
    # Abzug nur bei einheitlichem Satz: Steuerbasis 90, Steuer 17.10
    _beleg(pg_session, [("100.00", "19")], abzug="10.00", netto="90.00", steuer="17.10")

    assert _zeilen(pg_session) == {("S", Decimal("19"), "EUR"): (Decimal("90.00"), Decimal("17.10"))}
    assert _eur_summen(pg_session) == (nettoumsatz_ytd(pg_session, VON),
                                       schuldige_umsatzsteuer(pg_session, VON, BIS))


def test_beleg_ohne_positionen_oder_mit_abweichender_kopfsumme_bleibt_in_der_summe(pg_session):
    """Altbestand: die Kopfsumme gilt. Der Rest steht in einer Zeile ohne Satz."""
    _beleg(pg_session, [], netto="100.00", steuer="19.00")
    _beleg(pg_session, [("100.00", "19")], netto="105.00", steuer="19.95")

    netto, ust = _eur_summen(pg_session)

    assert (netto, ust) == (Decimal("205.00"), Decimal("38.95"))
    assert _zeilen(pg_session)[("S", None, "EUR")] == (Decimal("105.00"), Decimal("19.95"))


def test_andere_waehrung_steht_getrennt_und_nicht_in_eur(pg_session):
    _beleg(pg_session, [("100.00", "19")])
    _beleg(pg_session, [("500.00", "0")], kategorie="O", waehrung="USD")

    zeilen = _zeilen(pg_session)

    assert zeilen[("O", Decimal("0"), "USD")] == (Decimal("500.00"), Decimal("0.00"))
    assert ("O", Decimal("0"), "EUR") not in zeilen
    assert _eur_summen(pg_session)[0] == Decimal("100.00")
    # Die bestehenden Kennzahlen mischen Waehrungen (bekannte Vereinfachung):
    # sie ergeben EUR plus die nominalen Betraege fremder Waehrung.
    assert nettoumsatz_ytd(pg_session, VON) == Decimal("600.00")


def test_belegmenge_wie_kennzahlen_anzahlung_zeitraum_status(pg_session):
    _beleg(pg_session, [("100.00", "19")])
    _beleg(pg_session, [("100.00", "19")], status="draft")
    _beleg(pg_session, [("100.00", "19")], ausgestellt=BIS)  # halboffen: erst Folgequartal
    _beleg(pg_session, [("100.00", "19")], art="prepayment")  # unbezahlt: zaehlt nicht
    _beleg(pg_session, [("40.00", "19")], art="prepayment", status="paid",
           bezahlt_am=date(2026, 9, 20), ausgestellt=date(2026, 6, 1))  # nach Zahlung

    netto, ust = _eur_summen(pg_session)

    assert netto == Decimal("140.00")
    assert ust == Decimal("26.60")
    # Die Kennzahl ueber denselben Zeitraum nennt dieselben Zahlen.
    assert nettoumsatz_ytd(pg_session, VON) - nettoumsatz_ytd(pg_session, BIS) == netto
    assert schuldige_umsatzsteuer(pg_session, VON, BIS) == ust


def test_uebersicht_zeigt_aufstellung_des_laufenden_quartals(pg_session, client):
    from app.zeit import heute
    _beleg(pg_session, [("300.00", "0")], kategorie="AE", ausgestellt=heute())
    _beleg(pg_session, [("500.00", "0")], kategorie="O", ausgestellt=heute(), waehrung="USD")

    html = client.get("/dashboard").text

    assert "UMSATZ JE STEUERKATEGORIE" in html
    assert "AE" in html and "300,00" in html
    assert "USD" in html and "nicht umgerechnet" in html


def test_aufstellung_ohne_ende_nimmt_alles_ab_beginn(pg_session):
    _beleg(pg_session, [("100.00", "19")], ausgestellt=BIS)
    assert _zeilen(pg_session, VON, None) == {
        ("S", Decimal("19"), "EUR"): (Decimal("100.00"), Decimal("19.00"))}
