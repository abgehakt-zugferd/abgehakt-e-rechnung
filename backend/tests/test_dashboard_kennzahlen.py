"""Tests fuer Steuer-Kennzahlen auf der Uebersicht."""

from datetime import date
from decimal import Decimal

from app.services.dashboard_kennzahlen import (
    geschaetzte_steuerabgaben,
    nettoumsatz_ytd,
    schuldige_umsatzsteuer_ytd,
)
from app.services.steuer_ruecklage import steuerruecklage_anteil
from tests.test_steuer_ruecklage import _company


def test_schuldige_ust_summiert_gestellte_rechnungen(pg_session):
    from tests.test_dashboard import _gutschrift, _inv

    _inv(pg_session, "issued", "119.00", net=Decimal("100.00"), tax=Decimal("19.00"))
    _inv(pg_session, "draft", "119.00", net=Decimal("100.00"), tax=Decimal("19.00"))
    seit = date.today().replace(month=1, day=1)
    assert schuldige_umsatzsteuer_ytd(pg_session, seit) == Decimal("19.00")


def test_schuldige_ust_zieht_gutschriften_ab(pg_session):
    from tests.test_dashboard import _gutschrift, _inv

    _inv(pg_session, "issued", "119.00", net=Decimal("100.00"), tax=Decimal("19.00"))
    _gutschrift(
        pg_session, "issued", "59.50",
        net=Decimal("50.00"), tax=Decimal("9.50"),
    )
    seit = date.today().replace(month=1, day=1)
    assert schuldige_umsatzsteuer_ytd(pg_session, seit) == Decimal("9.50")


def test_geschaetzte_steuerabgaben_nutzt_firmeneinstellungen():
    netto = Decimal("1000.00")
    ust = Decimal("190.00")
    firma = _company(hebesatz=490)
    anteil = steuerruecklage_anteil(firma)
    assert geschaetzte_steuerabgaben(ust, netto, firma) == ust + netto * anteil


def test_nettoumsatz_ytd_ignoriert_gutschriften_netto(pg_session):
    from tests.test_dashboard import _gutschrift, _inv

    _inv(pg_session, "issued", "119.00", net=Decimal("100.00"), tax=Decimal("19.00"))
    _gutschrift(
        pg_session, "issued", "59.50",
        net=Decimal("50.00"), tax=Decimal("9.50"),
    )
    seit = date.today().replace(month=1, day=1)
    assert nettoumsatz_ytd(pg_session, seit) == Decimal("50.00")
