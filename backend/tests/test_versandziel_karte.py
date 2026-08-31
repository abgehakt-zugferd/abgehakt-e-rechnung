"""Empfaenger in der Rechnungsansicht sichtbar machen (#62).

Wohin ein Beleg geht, stand bisher allein im Aufklappmenue hinter SENDEN + DATEV:
ein Klick weit weg, erst nach dem Finalisieren und nur bei konfiguriertem SMTP.
Die Karte KUNDE sagt es jetzt ohne Klick, und zwar schon im Entwurf. Genau dort
ist es etwas wert: eine fehlende Adresse faellt auf, bevor eine Nummer vergeben
und der Beleg unveraenderlich ist.

Alle Faelle laufen bewusst gegen einen ENTWURF. Der Sende-Dialog wird fuer diesen
Status gar nicht gerendert, deshalb kann keine Zusicherung hier versehentlich
seinen Inhalt treffen statt den der Karte.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.models.invoice import Invoice


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _config(pg_session, **werte):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if not cfg:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    for k, v in werte.items():
        setattr(cfg, k, v)
    pg_session.commit()
    return cfg


def _entwurf(pg_session, kunde=None):
    inv = Invoice(invoice_number=f"RE-62-{uuid.uuid4().hex[:6]}",
                  customer_id=kunde.id if kunde else None,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status="draft")
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _kunde(pg_session, email="kunde@example.de", cc_emails=None):
    k = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München",
                 country="DE", email=email, cc_emails=cc_emails)
    pg_session.add(k)
    pg_session.commit()
    return k


def test_karte_zeigt_empfaenger_aus_dem_kundenstamm(pg_session):
    kunde = _kunde(pg_session, email="ines@example.de",
                   cc_emails="buchhaltung@example.de")
    inv = _entwurf(pg_session, kunde)
    _config(pg_session, datev_bcc_email="datev@example.de")

    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert r.status_code == 200
    assert "VERSAND AN" in r.text
    assert "ines@example.de" in r.text
    assert "buchhaltung@example.de" in r.text
    assert "aus dem Kundenstamm" in r.text
    # Der stille Dritte im Bunde gehoert genannt: der Steuerberater bekommt jeden
    # Beleg, und wer das nicht sieht, rechnet nicht damit.
    assert "DATEV Upload Mail" in r.text


def test_karte_nennt_die_voreinstellung_und_ihre_herkunft(pg_session):
    kunde = _kunde(pg_session, cc_emails=None)
    inv = _entwurf(pg_session, kunde)
    _config(pg_session, invoice_cc_email="ablage@example.de")

    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert "ablage@example.de" in r.text
    assert "aus den Einstellungen" in r.text


def test_karte_warnt_schon_im_entwurf_ohne_e_mail(pg_session):
    """Der eigentliche Gewinn: die Luecke faellt auf, solange sie noch behebbar
    ist. Das Finalisieren wird davon NICHT blockiert, eine Rechnung darf auch auf
    Papier gehen."""
    kunde = _kunde(pg_session, email=None)
    inv = _entwurf(pg_session, kunde)

    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert "Keine E-Mail hinterlegt" in r.text
    assert f"/customers/{kunde.id}/bearbeiten" in r.text


def test_karte_ohne_kunden_bleibt_unveraendert(pg_session):
    """Ein Entwurf ohne Kunden hat keinen Empfaenger, ueber den sich etwas sagen
    liesse. Der bestehende Kasten mit dem Weg zum Anlegen bleibt, wie er war."""
    inv = _entwurf(pg_session, kunde=None)

    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert "Noch keiner zugeordnet" in r.text
    assert "VERSAND AN" not in r.text
