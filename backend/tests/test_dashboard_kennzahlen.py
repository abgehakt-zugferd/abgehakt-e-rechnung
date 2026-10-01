"""Tests fuer Steuer-Kennzahlen und Belegaggregationen auf der Uebersicht."""

from datetime import date
from app.zeit import heute
from decimal import Decimal

from app.services.dashboard_kennzahlen import (
    belegzaehlung,
    bezahlt_im_zeitraum,
    geschaetzte_steuerabgaben,
    nettoumsatz_ytd,
    nicht_versendet_anzahl,
    offene_forderungen,
    schuldige_umsatzsteuer,
    schuldige_umsatzsteuer_ytd,
    ueberfaellige_forderungen,
    umsatz_abweichung_prozent,
    umsatz_im_zeitraum,
    vorjahres_stichtag,
)
from app.services.steuer_ruecklage import steuerruecklage_anteil
from tests.test_steuer_ruecklage import _company


def test_schuldige_ust_summiert_gestellte_rechnungen(pg_session):
    from tests.test_dashboard import _gutschrift, _inv

    _inv(pg_session, "issued", "119.00", net=Decimal("100.00"), tax=Decimal("19.00"))
    _inv(pg_session, "draft", "119.00", net=Decimal("100.00"), tax=Decimal("19.00"))
    seit = heute().replace(month=1, day=1)
    assert schuldige_umsatzsteuer_ytd(pg_session, seit) == Decimal("19.00")


def test_schuldige_ust_zieht_gutschriften_ab(pg_session):
    from tests.test_dashboard import _gutschrift, _inv

    _inv(pg_session, "issued", "119.00", net=Decimal("100.00"), tax=Decimal("19.00"))
    _gutschrift(
        pg_session, "issued", "59.50",
        net=Decimal("50.00"), tax=Decimal("9.50"),
    )
    seit = heute().replace(month=1, day=1)
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
    seit = heute().replace(month=1, day=1)
    assert nettoumsatz_ytd(pg_session, seit) == Decimal("50.00")


def test_offener_betrag_summiert_nur_issued(pg_session):
    from tests.test_dashboard import _inv

    _inv(pg_session, "issued", "100.00")
    _inv(pg_session, "issued", "50.00")
    _inv(pg_session, "draft", "200.00")
    _inv(pg_session, "paid", "300.00")
    _inv(pg_session, "cancelled", "400.00")
    posten = offene_forderungen(pg_session)
    assert posten.anzahl == 2
    assert posten.betrag == Decimal("150.00")


def test_offene_forderungen_ignorieren_gutschrift(pg_session):
    from tests.test_dashboard import _gutschrift, _inv

    _inv(pg_session, "issued", "100.00")
    _gutschrift(pg_session, "issued", "50.00")
    posten = offene_forderungen(pg_session)
    assert posten.anzahl == 1
    assert posten.betrag == Decimal("100.00")


def test_faellig_heute_ist_nicht_ueberfaellig(pg_session):
    from tests.test_dashboard import _inv

    heute = date(2026, 9, 28)
    _inv(pg_session, "issued", "100.00", due=heute)
    ergebnis = ueberfaellige_forderungen(pg_session, heute)
    assert ergebnis.anzahl == 0
    assert ergebnis.betrag == Decimal("0")
    assert ergebnis.aeltester_tage is None


def test_faellig_gestern_ist_ueberfaellig(pg_session):
    from tests.test_dashboard import _inv

    heute = date(2026, 9, 28)
    _inv(pg_session, "issued", "100.00", due=date(2026, 9, 27))
    ergebnis = ueberfaellige_forderungen(pg_session, heute)
    assert ergebnis.anzahl == 1
    assert ergebnis.betrag == Decimal("100.00")
    assert ergebnis.aeltester_tage == 1


def test_aeltester_tage_nimmt_kleinstes_due_date(pg_session):
    from tests.test_dashboard import _inv

    heute = date(2026, 9, 28)
    _inv(pg_session, "issued", "10.00", due=date(2026, 9, 20))
    _inv(pg_session, "issued", "20.00", due=date(2026, 9, 10))
    ergebnis = ueberfaellige_forderungen(pg_session, heute)
    assert ergebnis.anzahl == 2
    assert ergebnis.aeltester_tage == 18


def test_vormonat_enthalt_laufenden_monat_nicht(pg_session):
    from tests.test_dashboard import _inv

    monat_beginn = date(2026, 9, 1)
    vormonat_beginn = date(2026, 8, 1)

    _inv(
        pg_session, "paid", "100.00",
        issue=date(2026, 8, 15), bezahlt_am=date(2026, 9, 10),
    )
    _inv(
        pg_session, "paid", "40.00",
        issue=date(2026, 7, 15), bezahlt_am=date(2026, 8, 20),
    )

    assert bezahlt_im_zeitraum(pg_session, vormonat_beginn, monat_beginn) == Decimal("40.00")
    assert bezahlt_im_zeitraum(pg_session, monat_beginn, None) == Decimal("100.00")


def test_vorjahres_stichtag_am_29_februar():
    assert vorjahres_stichtag(date(2024, 2, 29)) == date(2023, 2, 28)


def test_umsatz_vorjahr_null_liefert_keine_prozentzahl(pg_session):
    from tests.test_dashboard import _inv

    _inv(
        pg_session, "paid", "100.00",
        issue=date(2026, 3, 1), bezahlt_am=date(2026, 3, 1),
    )
    vorjahr = umsatz_im_zeitraum(
        pg_session, date(2025, 1, 1), date(2025, 3, 15),
    )
    assert vorjahr == Decimal("0")
    assert umsatz_abweichung_prozent(Decimal("100.00"), vorjahr) is None


def test_quartals_ust_ohne_vorquartal(pg_session):
    from tests.test_dashboard import _inv

    _inv(
        pg_session, "issued", "119.00",
        issue=date(2026, 5, 10),
        net=Decimal("100.00"), tax=Decimal("19.00"),
    )
    _inv(
        pg_session, "issued", "238.00",
        issue=date(2026, 8, 10),
        net=Decimal("200.00"), tax=Decimal("38.00"),
    )
    # Q3 2026 beginnt am 1. Juli
    assert schuldige_umsatzsteuer(pg_session, date(2026, 7, 1), None) == Decimal("38.00")


def test_nicht_versendet_zaehlt_nur_issued_ohne_versand(pg_session):
    from datetime import datetime, timezone

    from tests.test_dashboard import _gutschrift, _inv

    offen = _inv(pg_session, "issued", "100.00")
    versendet = _inv(pg_session, "issued", "50.00")
    versendet.datev_sent_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    _inv(pg_session, "draft", "10.00")
    _inv(pg_session, "paid", "20.00")
    _gutschrift(pg_session, "issued", "30.00")
    pg_session.commit()
    assert nicht_versendet_anzahl(pg_session) == 1
    assert offen.status == "issued"


def test_belegzaehlung_teilt_status_auf(pg_session):
    from tests.test_dashboard import _inv

    for _ in range(2):
        _inv(pg_session, "draft", "0")
    for _ in range(3):
        _inv(pg_session, "issued", "100.00")
    for _ in range(4):
        _inv(pg_session, "paid", "50.00")
    for _ in range(5):
        _inv(pg_session, "cancelled", "0")
    _inv(pg_session, "discarded", "0")
    z = belegzaehlung(pg_session)
    assert z.gesamt == 15
    assert z.entwurf == 2
    assert z.gestellt == 3
    assert z.bezahlt == 4
    assert z.storniert == 5
