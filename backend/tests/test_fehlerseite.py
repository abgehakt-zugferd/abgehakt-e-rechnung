"""
Fehler erscheinen als Seite, nicht als JSON.

Rund 45 `raise HTTPException(...)` liegen in den Routern, und jeder davon endete
bisher als `{"detail": "..."}` auf weißem Grund. Die Meldungen sind fachlich
sorgfältig formuliert (§ 14 UStG, Statusmaschine, fail-closed) — sie erreichen
den Menschen aber nur, wenn sie im Layout der Anwendung stehen, mit einem Weg
zurück. Ein Formular-POST landet sonst in einer geschweiften Klammer.

Der Rückweg ist der eigentliche Punkt: nach einem POST ist die vorige Seite
nicht wiederherstellbar (`Cache-Control: no-store` auf den Anlegeformularen),
der Nutzer hängt ohne Navigation fest.

Echtes Postgres, weil das Gate beim Finalisieren nur mit echtem Validator und
echter Sitzung scharf ist.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _draft(pg_session, *, delivery_date: date | None = date(2026, 7, 8)):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    # Über 250 € brutto: erst ab dieser Schwelle verlangt § 14 Abs. 4 Nr. 6 UStG
    # den Leistungszeitpunkt. Mit kleineren Beträgen prüfte der Test eine andere
    # Meldung als die, die einen Ersteinrichter wirklich trifft.
    net, tax, gross = Decimal("300.00"), Decimal("57.00"), Decimal("357.00")
    inv = Invoice(invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 7, 8), delivery_date=delivery_date,
                  due_date=date(2026, 7, 22), currency="EUR", zugferd_profile="EN16931",
                  tax_category="S", status="draft",
                  payment_terms="Zahlbar in 14 Tagen.",
                  net_total=net, tax_total=tax, gross_total=gross)
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("1"), unit_price=net,
                             tax_rate=Decimal("19"), net_amount=net,
                             tax_amount=tax, gross_amount=gross)]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_abgewiesenes_finalisieren_kommt_als_html_zurueck(pg_session):
    """Der § 14-Fehler beim Finalisieren ist die Meldung, die am häufigsten jemanden
    trifft, der das Programm zum ersten Mal benutzt. Sie muss lesbar ankommen."""
    inv = _draft(pg_session, delivery_date=None)

    r = _client(pg_session).post(f"/invoices/{inv.id}/finalisieren")

    assert r.status_code == 400
    assert r.headers["content-type"].startswith("text/html")
    assert '{"detail"' not in r.text
    assert "Zeitpunkt der Leistungserbringung fehlt" in r.text


def test_fehlerseite_traegt_das_layout_der_anwendung(pg_session):
    """Ohne das Grundgerüst wäre es weiterhin eine nackte Seite — nur mit Fließtext
    statt mit JSON. Die Navigation ist der Weg zurück."""
    inv = _draft(pg_session, delivery_date=None)

    r = _client(pg_session).post(f"/invoices/{inv.id}/finalisieren")

    assert 'href="/dashboard"' in r.text
    assert 'href="/invoices"' in r.text


def test_unbekannte_adresse_zeigt_eine_seite(pg_session):
    """Ein 404 auf einer nicht vergebenen Adresse trifft die App-weite Abhängigkeit
    `load_update_banner` NICHT — sie läuft erst, wenn eine Route zugeordnet ist.
    `base.html` liest aber `request.state.update_banner`. Die Fehlerseite darf
    daran nicht selbst zerbrechen (sonst 500 statt 404)."""
    r = _client(pg_session).get("/eine-adresse-die-es-nicht-gibt")

    assert r.status_code == 404
    assert r.headers["content-type"].startswith("text/html")
    assert '{"detail"' not in r.text
    assert 'href="/dashboard"' in r.text


def test_fehlerseite_ohne_meldung_bleibt_verstaendlich(pg_session):
    """Mehrere Stellen werfen `HTTPException(404)` ohne Text. Starlette setzt dann
    "Not Found" ein — englisch und nichtssagend. Die Seite muss trotzdem auf Deutsch
    erklären, was los ist."""
    r = _client(pg_session).post(f"/invoices/{uuid.uuid4()}/finalisieren")

    assert r.status_code == 404
    assert "Not Found" not in r.text
    assert "nicht gefunden" in r.text.lower()


def test_unbrauchbare_eingabe_kommt_als_seite_ohne_interna(pg_session):
    """Ein unlesbares Datum im GoBD-Export wird nicht von `HTTPException` erfasst,
    sondern von Pydantic (`RequestValidationError`) — ein zweiter Weg, der ohne
    eigenen Behandler weiterhin als JSON herauskäme.

    Der Rohtext von Pydantic ist englisch und nennt Feldpfade und Fehlertypen
    (`date_from_datetime_parsing`, `loc`). Das gehört nicht auf den Bildschirm
    eines Rechnungsprogramms: es hilft niemandem und verrät den inneren Aufbau.
    """
    r = _client(pg_session).get("/export/gobd?von=kaputt&bis=2026-12-31")

    assert r.status_code == 422
    assert r.headers["content-type"].startswith("text/html")
    assert '{"detail"' not in r.text
    assert "date_from_datetime_parsing" not in r.text
    assert '"loc"' not in r.text
    assert 'href="/dashboard"' in r.text


def test_fremder_text_in_der_meldung_wird_maskiert(pg_session):
    """`/status` schreibt den abgeschickten Zielstatus in die Meldung. Sobald die
    Meldung als HTML gerendert wird, ist das ein Einfallstor — der Wert kommt aus
    dem Formular. Jinja maskiert automatisch; dieser Test hält das fest, damit ein
    späteres `|safe` in der Vorlage auffällt."""
    inv = _draft(pg_session)

    r = _client(pg_session).post(f"/invoices/{inv.id}/status",
                                 data={"new_status": "<script>alert(1)</script>"})

    assert r.status_code == 400
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text
