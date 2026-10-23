"""Ersteinrichtung offen trotz gespeicherter Firmendaten (#205).

Zwei Wege schreiben dieselben Firmendaten; nur einer setzte bisher
`setup_completed_at`. Die Wirkungen melden denselben Text, und auf der
Uebergabeliste ist `/setup` ein Link ohne freies HTML in Fehlertexten.
"""

from __future__ import annotations

import html
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app.models.app_config import AppConfig
from app.models.company import Company
from app.models.customer import Customer
from app.services.abrechnungsauftrag_wirkung import (
    WirkungFehler,
    entwuerfe_anlegen,
)
from app.services.ersteinrichtung import ERSTEINRICHTUNG_OFFEN_MELDUNG
from app.services.rechnungsauftrag_wirkung import entwurf_anlegen
from app.services.uebergabe_befund import Belegurteil
from app.services.uebergabebeleg import ABSENDER_TANTIEMEN
from tests.helpers.uebergabe import PARTNER_A, beleg, rechnungsauftrag
from tests.probe_daten import HRB_PROBE, STEUER_PROBE_ZEHN

ERZEUGT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)
PARTNER_UUID = uuid.UUID(PARTNER_A)


def _firma_offen(pg_session):
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    firma.setup_completed_at = None
    pg_session.commit()
    return firma


def _firma_form(**extra):
    data = {
        "name": "Muster Handwerk GmbH",
        "address_line1": "Musterstraße 1",
        "zip_code": "12345",
        "city": "Musterstadt",
        "country": "DE",
        "tax_number": STEUER_PROBE_ZEHN,
        "rechtsform": "gmbh",
        "registergericht": "Amtsgericht Musterstadt",
        "registernummer": HRB_PROBE,
        "vertretung": "Probe Geschäftsführerin",
        "invoice_prefix": "RE",
        "kst_satz_percent": "15",
        "soli_auf_kst_percent": "5,5",
        "gewerbe_hebesatz": "400",
        "payment_terms_default": "Zahlbar innerhalb von 14 Tagen ohne Abzug.",
        "payment_terms_default_en": "Payable within 14 days without deduction.",
    }
    data.update(extra)
    return data


def _kunde_rechnungsauftrag(pg_session):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Beispiel GmbH",
        address_line1="Platz 1",
        zip_code="1015",
        city="Amsterdam",
        country="NL",
        auftrag_steuer="AE",
        vat_id="NL123456789B01",
    )
    kunde.id = PARTNER_UUID
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _kunde_abrechnungsauftrag(pg_session):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Beispiel Autorin",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        gutschriftempfaenger=True,
        ust_status="regelbesteuert",
        tax_number=STEUER_PROBE_ZEHN,
    )
    kunde.id = PARTNER_UUID
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _urteil_rechnungsauftrag():
    return Belegurteil(
        beleg_sha256="a" * 64,
        beleg_id="11111111-2222-4333-8444-555555555556",
        angenommen=True,
        absender=ABSENDER_TANTIEMEN,
        nutzlast_art="rechnungsauftrag",
        erzeugt_am=ERZEUGT,
        nutzlast=rechnungsauftrag(),
    )


def _urteil_abrechnungsauftrag():
    nutzlast = {
        "abrechnungsquartal": "2026-Q2",
        "projekt": {"id": "probe", "name": "Probeverlag"},
        "bemessung": {
            "erloes_netto": "797.30",
            "direktkosten_netto": "100.00",
            "deckungsbeitrag_netto": "697.30",
        },
        "grundlagen": [],
        "gutschriften": [{
            "beteiligter": {
                "partner_id": PARTNER_A,
                "anzeigename": "Beispiel Autorin",
            },
            "typcode": "389",
            "leistungszeitraum": {"von": "2026-04-01", "bis": "2026-06-30"},
            "positionen": [{
                "nr": 1,
                "bezeichnung": "Beteiligung am Deckungsbeitrag 2026-Q2",
                "herleitung": {"basis_netto": "697.30", "satz": "25.00"},
                "netto": "174.33",
            }],
            "summe": {"netto": "174.33"},
        }],
        "vortraege": [],
    }
    return Belegurteil(
        beleg_sha256="b" * 64,
        beleg_id="c0c0c0c0-0000-4000-8000-000000000001",
        angenommen=True,
        absender=ABSENDER_TANTIEMEN,
        nutzlast_art="abrechnungsauftrag",
        erzeugt_am=ERZEUGT,
        nutzlast=nutzlast,
        gegenstand="Probeverlag",
        zeitraum="2026-Q2",
        summe="174,33",
    )


def test_rechnungsauftrag_meldet_dieselbe_ersteinrichtung_meldung(pg_session):
    _firma_offen(pg_session)
    _kunde_rechnungsauftrag(pg_session)

    with pytest.raises(WirkungFehler, match=re.escape(ERSTEINRICHTUNG_OFFEN_MELDUNG)):
        entwurf_anlegen(pg_session, _urteil_rechnungsauftrag())


def test_abrechnungsauftrag_meldet_dieselbe_ersteinrichtung_meldung(pg_session):
    _firma_offen(pg_session)
    _kunde_abrechnungsauftrag(pg_session)

    with pytest.raises(WirkungFehler, match=re.escape(ERSTEINRICHTUNG_OFFEN_MELDUNG)):
        entwuerfe_anlegen(pg_session, _urteil_abrechnungsauftrag())


def test_settings_firma_schliesst_einrichtung_bei_pflichtangaben(pg_session, client):
    _firma_offen(pg_session)

    antwort = client.post("/settings/firma", data=_firma_form())

    assert antwort.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Company, 1).setup_completed_at is not None


def test_settings_firma_ohne_steuer_schliesst_nicht_ab(pg_session, client):
    _firma_offen(pg_session)

    antwort = client.post(
        "/settings/firma",
        data=_firma_form(tax_number="", vat_id=""),
    )

    assert antwort.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Company, 1).setup_completed_at is None


def test_settings_firma_setzt_setup_completed_at_nicht_zurueck(pg_session, client):
    firma = pg_session.get(Company, 1)
    vorher = datetime(2026, 7, 1, tzinfo=timezone.utc)
    firma.setup_completed_at = vorher
    pg_session.commit()

    antwort = client.post(
        "/settings/firma",
        data=_firma_form(tax_number="", vat_id=""),
    )

    assert antwort.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Company, 1).setup_completed_at == vorher


def test_uebergaben_fehler_zeigt_setup_als_link_ohne_fremdes_html(
    client, pg_session,
):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.beleg_integration_aktiv = True
    pg_session.commit()

    roh = (
        'Vorher <script>alert(1)</script> '
        + ERSTEINRICHTUNG_OFFEN_MELDUNG
        + ' danach'
    )
    seite = client.get("/uebergaben", params={"fehler": roh})

    assert seite.status_code == 200
    assert "<script>alert(1)</script>" not in seite.text
    assert "&lt;script&gt;" in seite.text
    assert 'href="/setup"' in seite.text
    assert re.search(r'<a href="/setup">/setup</a>', seite.text)


def test_wirkung_fehler_erreicht_uebergaben_mit_setup_link(
    client, pg_session, tmp_path,
):
    from app.config import get_settings
    from tests.helpers.uebergabe import schluesselpaar

    _firma_offen(pg_session)
    _kunde_abrechnungsauftrag(pg_session)

    ordner = tmp_path / "uebergaben"
    richtung = ordner / "tantiemen-app-nach-abgehakt"
    richtung.mkdir(parents=True)
    signieren, schluessel = schluesselpaar(tmp_path / "schluessel")
    einstellungen = get_settings()
    vorher = (einstellungen.uebergaben_ordner, einstellungen.schluessel_pfad)
    einstellungen.uebergaben_ordner = str(ordner)
    einstellungen.schluessel_pfad = str(schluessel)

    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.beleg_integration_aktiv = True
    pg_session.commit()

    (richtung / "auftrag.json").write_bytes(beleg(signieren))
    try:
        antwort = client.post("/uebergaben/auftrag.json/rechnung-anlegen")
        assert antwort.status_code == 303
        ort = antwort.headers["location"]
        meldung = parse_qs(urlparse(ort).query)["fehler"][0]
        assert meldung == ERSTEINRICHTUNG_OFFEN_MELDUNG

        seite = client.get(ort)
        assert seite.status_code == 200
        assert ERSTEINRICHTUNG_OFFEN_MELDUNG.split("/setup")[0] in html.unescape(
            seite.text
        )
        assert 'href="/setup"' in seite.text
    finally:
        einstellungen.uebergaben_ordner, einstellungen.schluessel_pfad = vorher
