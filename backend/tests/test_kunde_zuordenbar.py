"""#173: Nur aktive, nicht geloeschte Kunden sind einem Beleg zuordenbar."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.abrechnungsauftrag_wirkung import WirkungFehler, entwuerfe_anlegen
from app.services.invoice_guard import register_invoice_guard
from app.services.rechnungsauftrag_wirkung import entwurf_anlegen
from app.services.uebergabe_befund import Belegurteil
from app.services.validator import validate_invoice
from tests.helpers.uebergabe import PARTNER_A, rechnungsauftrag

register_invoice_guard()
ERZEUGT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)
MELDUNG_DEAKTIVIERT = "Kunde ist deaktiviert"


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde(pg_session, *, is_active=True, deleted_at=None, name="Beispiel GmbH", **extra):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
        address_line1="Beispielweg 1", zip_code="80331", city="Muenchen",
        country="DE", is_active=is_active, deleted_at=deleted_at, **extra,
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _beleg(pg_session, kunde, *, status="issued"):
    inv = Invoice(
        invoice_number=f"RE-KZ-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
        issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15),
        delivery_date=date(2026, 6, 1), currency="EUR", tax_category="S",
        status=status, net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"), payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.items = [InvoiceItem(
        position=1, description="Beratung", unit="Stunde",
        quantity=Decimal("1"), unit_price=Decimal("100.00"),
        tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
        tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"),
    )]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _neu_payload(kunde_id):
    return {
        "customer_id": str(kunde_id),
        "issue_date": "2026-06-11", "due_date": "2026-06-25",
        "tax_category": "S",
        "items_json": json.dumps([{
            "description": "Beratung", "unit": "Stunde",
            "quantity": "1", "unit_price": "100", "tax_rate": "19",
        }]),
    }


def _stamm(pg_session, kennung, *, is_active=True, **felder):
    angaben = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autorin A",
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
        gutschriftempfaenger=True, ust_status="regelbesteuert",
        tax_number="12/345/67890", is_active=is_active,
    )
    angaben.update(felder)
    kunde = Customer(**angaben)
    kunde.id = uuid.UUID(str(kennung))
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _abrechnungs_urteil(partner_id=PARTNER_A):
    return Belegurteil(
        beleg_sha256="1" * 64,
        beleg_id="c0c0c0c0-0000-4000-8000-000000000001",
        angenommen=True, absender="tantiemen-app",
        nutzlast_art="abrechnungsauftrag", erzeugt_am=ERZEUGT,
        nutzlast={
            "abrechnungsquartal": "2026-Q2",
            "projekt": {"id": "probe", "name": "Probeverlag"},
            "bemessung": {
                "erloes_netto": "797.30", "direktkosten_netto": "100.00",
                "deckungsbeitrag_netto": "697.30",
            },
            "grundlagen": [], "vortraege": [],
            "gutschriften": [{
                "beteiligter": {
                    "partner_id": str(partner_id), "anzeigename": "Autorin A",
                },
                "typcode": "389",
                "leistungszeitraum": {"von": "2026-04-01", "bis": "2026-06-30"},
                "positionen": [{
                    "nr": 1, "bezeichnung": "Beteiligung",
                    "herleitung": {"basis_netto": "697.30", "satz": "25.00"},
                    "netto": "174.33",
                }],
                "summe": {"netto": "174.33"},
            }],
        },
        abrechnungsquartal="2026-Q2", projekt="Probeverlag",
        zahl_gutschriften=1, summe_netto=Decimal("174.33"),
    )


def _rechnungs_urteil():
    return Belegurteil(
        beleg_sha256="2" * 64,
        beleg_id="11111111-2222-4333-8444-555555555556",
        angenommen=True, absender="tantiemen-app",
        nutzlast_art="rechnungsauftrag", erzeugt_am=ERZEUGT,
        nutzlast=rechnungsauftrag(),
    )


# --- Formular: Neu und Bearbeiten --------------------------------------------


def test_b_post_neu_lehnt_deaktivierten_kunden_ab(pg_session):
    """Gewuenscht: POST /neu mit is_active=False schlaegt fehl."""
    kunde = _kunde(pg_session, is_active=False)

    r = _client(pg_session).post("/invoices/neu", data=_neu_payload(kunde.id))

    assert r.status_code == 400, (
        f"Entwurf fuer deaktivierten Kunden angelegt (HTTP {r.status_code})"
    )
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).count() == 0


def test_b_post_neu_lehnt_geloeschten_kunden_ab(pg_session):
    """Gewuenscht: POST /neu mit deleted_at gesetzt schlaegt fehl."""
    kunde = _kunde(
        pg_session,
        deleted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    r = _client(pg_session).post("/invoices/neu", data=_neu_payload(kunde.id))

    assert r.status_code == 400, (
        f"Entwurf fuer geloeschten Kunden angelegt (HTTP {r.status_code})"
    )
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).count() == 0


def test_b_bearbeiten_setzt_keinen_deaktivierten_empfaenger(pg_session):
    """Gewuenscht: Bearbeiten wechselt nicht auf deaktivierten Kunden."""
    aktiv = _kunde(pg_session, name="Aktiv Beispiel GmbH")
    inaktiv = _kunde(pg_session, is_active=False, name="Inaktiv Beispiel GmbH")
    entwurf = _beleg(pg_session, aktiv, status="draft")

    r = _client(pg_session).post(
        f"/invoices/{entwurf.id}/bearbeiten",
        data=_neu_payload(inaktiv.id),
    )

    assert r.status_code == 400, (
        f"Empfaenger auf deaktiviert gesetzt (HTTP {r.status_code})"
    )
    pg_session.expire_all()
    assert pg_session.get(Invoice, entwurf.id).customer_id == aktiv.id


def test_b_validator_laesst_deaktivierten_kunden_nicht_durch(pg_session):
    """Gewuenscht: Finalisieren-Validator faengt is_active=False noch ab."""
    kunde = _kunde(pg_session, is_active=False)
    entwurf = _beleg(pg_session, kunde, status="draft")
    firma = pg_session.query(Company).filter(Company.id == 1).one()

    errors, _warnings = validate_invoice(entwurf, firma)
    codes = {e.code for e in errors}

    assert codes, (
        "Validator akzeptiert deaktivierten Kunden; Finalisieren waere nicht geblockt"
    )


# --- Uebergabe: Anwenden auf deaktivierten Kunden ----------------------------


def test_abrechnungsauftrag_anwenden_auf_deaktivierten_kunden_bricht_ab(pg_session):
    _stamm(pg_session, PARTNER_A, is_active=False)

    with pytest.raises(WirkungFehler) as befund:
        entwuerfe_anlegen(pg_session, _abrechnungs_urteil(), dateiname="a.json")

    assert str(befund.value) == MELDUNG_DEAKTIVIERT
    pg_session.rollback()
    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_rechnungsauftrag_anwenden_auf_deaktivierten_kunden_bricht_ab(pg_session):
    _stamm(
        pg_session, PARTNER_A, is_active=False, name="Plattform Beispiel GmbH",
        address_line1="Platz 1", zip_code="1015", city="Amsterdam", country="NL",
        gutschriftempfaenger=False, ust_status="ungeklaert", tax_number=None,
        auftrag_steuer="AE", vat_id="NL123456789B01",
    )

    with pytest.raises(WirkungFehler) as befund:
        entwurf_anlegen(pg_session, _rechnungs_urteil(), dateiname="r.json")

    assert str(befund.value) == MELDUNG_DEAKTIVIERT
    pg_session.rollback()
    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_abrechnungsauftrag_unbekannter_kunde_bleibt_bei_alter_meldung(pg_session):
    """Gegenprobe: unbekannt/geloescht ≠ deaktiviert."""
    with pytest.raises(WirkungFehler) as befund:
        entwuerfe_anlegen(pg_session, _abrechnungs_urteil(), dateiname="a.json")

    assert str(befund.value) == f"Kein Kunde zu partner_id {PARTNER_A}"
    assert MELDUNG_DEAKTIVIERT not in str(befund.value)


# --- Gestellter Beleg bleibt nutzbar ----------------------------------------


def test_gestellter_beleg_bleibt_nach_deaktivierung_sichtbar(pg_session):
    """Bereits gestellte Belege eines spaeter deaktivierten Kunden bleiben."""
    kunde = _kunde(pg_session)
    beleg = _beleg(pg_session, kunde, status="issued")
    kunde.is_active = False
    pg_session.commit()

    r = _client(pg_session).get(f"/invoices/{beleg.id}")

    assert r.status_code == 200
    assert beleg.invoice_number in r.text
