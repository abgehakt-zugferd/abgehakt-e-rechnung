"""Das Änderungsprotokoll gehört in die Oberfläche (#154).

Die Einträge in `audit_log` waren vollständig und landeten im Prüfungsexport, aber
sie waren nirgends zu sehen. Wer wissen wollte, was mit einer Rechnung passiert ist,
musste einen GoBD-Export ziehen und eine CSV lesen.

Zwei Gründe, das zu ändern:

1. Nachvollziehbarkeit nützt dem Nutzer, nicht nur dem Prüfer. „Wann habe ich die
   abgeschickt?" ist eine Alltagsfrage.
2. Ein Protokoll, das niemand ansieht, wird nicht bemerkt, wenn es ausfällt. Fiele
   der Session-Listener aus, merkte es sonst frühestens der nächste Export, also
   womöglich in Jahren.

Deshalb prüft dieser Test auch, dass das Protokoll die echten Ereignisse zeigt und
nicht eine leere Liste, die immer freundlich aussieht.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.aenderungsprotokoll import protokoll_fuer


def teardown_function():
    app.dependency_overrides.clear()


def _rechnung(pg_session) -> Invoice:
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                     address_line1="Weg 1", zip_code="80331", city="München",
                     country="DE")
    pg_session.add(kunde)
    pg_session.flush()

    rechnung = Invoice(
        invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
        issue_date=date(2026, 8, 9), due_date=date(2026, 8, 23),
        net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"), status="draft",
    )
    rechnung.items = [InvoiceItem(
        position=1, description="Leistung", quantity=Decimal("1"), unit="Stück",
        unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"),
    )]
    pg_session.add(rechnung)
    pg_session.commit()
    return rechnung


# ── Der Dienst: aus Ereignisnamen wird Sprache ──────────────────────────────

def test_das_anlegen_steht_als_erstes_ereignis_im_protokoll(pg_session):
    rechnung = _rechnung(pg_session)

    zeilen = protokoll_fuer(pg_session, rechnung.id)

    assert zeilen, "Protokoll leer, obwohl die Rechnung gerade angelegt wurde"
    assert zeilen[-1].vorgang == "Entwurf angelegt"


def test_das_finalisieren_heisst_finalisiert_und_nicht_update(pg_session):
    """Rohe Ereignisnamen (`update`) sagen dem Nutzer nichts. Der Statuswechsel
    ist die Information, nicht die Tatsache, dass eine Zeile geschrieben wurde."""
    rechnung = _rechnung(pg_session)
    rechnung.status = "issued"
    pg_session.commit()

    zeilen = protokoll_fuer(pg_session, rechnung.id)

    assert zeilen[0].vorgang == "Finalisiert"


def test_der_versand_wird_als_versand_benannt(pg_session):
    from datetime import datetime, timezone

    rechnung = _rechnung(pg_session)
    rechnung.status = "issued"
    pg_session.commit()
    rechnung.datev_sent_at = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    pg_session.commit()

    zeilen = protokoll_fuer(pg_session, rechnung.id)

    assert zeilen[0].vorgang == "An DATEV gesendet"


def test_das_neueste_ereignis_steht_oben(pg_session):
    rechnung = _rechnung(pg_session)
    rechnung.status = "issued"
    pg_session.commit()

    zeilen = protokoll_fuer(pg_session, rechnung.id)

    assert len(zeilen) >= 2
    assert zeilen[0].zeitpunkt >= zeilen[-1].zeitpunkt


def test_geaenderte_felder_stehen_auf_deutsch_da(pg_session):
    rechnung = _rechnung(pg_session)
    rechnung.payment_terms = "Zahlbar sofort."
    pg_session.commit()

    zeilen = protokoll_fuer(pg_session, rechnung.id)

    assert "Zahlungsbedingungen" in zeilen[0].felder, zeilen[0].felder


# ── Das Anlegen ist EIN Vorgang, auch wenn es zwei Zeilen schreibt ──────────

def test_das_anlegen_erscheint_nicht_als_bearbeitung(pg_session):
    """Gefunden in der Abnahme (10.08.2026).

    `create_invoice` schreibt die Rechnung, holt sich per `flush()` die ID und
    setzt danach Summen und Aufbewahrungsfrist: ein `INSERT` und ein `UPDATE`,
    beide in DERSELBEN Transaktion. Das Protokoll zeigte daraufhin neben
    "Entwurf angelegt" eine zweite Zeile "Bearbeitet: Nettobetrag, Bruttobetrag,
    Aufbewahrung bis" -- eine Bearbeitung, die nie stattgefunden hat.

    Das ist keine Kleinigkeit, sondern trifft genau den Zweck der Anzeige: Wer
    wissen will, ob jemand an seiner Rechnung war, darf keine Aenderung
    vorgefuehrt bekommen, die es nicht gab. Erkennungsmerkmal ist der Zeitpunkt:
    `changed_at` ist ein `now()` der Datenbank und damit fuer alle Zeilen einer
    Transaktion identisch.
    """
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                     address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(kunde)
    pg_session.commit()

    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    antwort = client.post("/invoices/neu", data={
        "customer_id": str(kunde.id),
        "issue_date": "2026-08-10",
        "due_date": "2026-08-24",
        "tax_category": "S",
        "items_json": '[{"description":"Leistung","unit":"Std","quantity":"1",'
                      '"unit_price":"100.00","tax_rate":"19"}]',
    })
    rechnung_id = antwort.headers["location"].rsplit("/", 1)[1]

    zeilen = protokoll_fuer(pg_session, rechnung_id)

    assert [z.vorgang for z in zeilen] == ["Entwurf angelegt"], \
        [(z.vorgang, z.felder) for z in zeilen]


def test_eine_echte_bearbeitung_bleibt_sichtbar(pg_session):
    """Die Gegenprobe. Ohne sie koennte das Zusammenfassen jede Bearbeitung
    schlucken und der Test oben bliebe gruen."""
    rechnung = _rechnung(pg_session)
    rechnung.payment_terms = "Zahlbar sofort."
    pg_session.commit()

    zeilen = protokoll_fuer(pg_session, rechnung.id)

    assert [z.vorgang for z in zeilen] == ["Bearbeitet", "Entwurf angelegt"], \
        [z.vorgang for z in zeilen]


def test_fremde_rechnungen_tauchen_nicht_auf(pg_session):
    """Der Bezug ist Tabelle UND Datensatz. Nur auf `record_id` zu filtern wäre
    hier zufällig richtig und beim nächsten Modell falsch."""
    eine = _rechnung(pg_session)
    andere = _rechnung(pg_session)
    andere.status = "issued"
    pg_session.commit()

    zeilen = protokoll_fuer(pg_session, eine.id)

    assert all(z.vorgang == "Entwurf angelegt" for z in zeilen), \
        [z.vorgang for z in zeilen]


# ── Die Seite: sichtbar, lesbar, unveränderlich ─────────────────────────────

def test_die_detailseite_zeigt_das_protokoll(pg_session):
    rechnung = _rechnung(pg_session)
    rechnung.status = "issued"
    pg_session.commit()
    app.dependency_overrides[get_db] = lambda: pg_session

    html = TestClient(app).get(f"/invoices/{rechnung.id}").text

    assert "ÄNDERUNGSPROTOKOLL" in html.upper()
    assert "Finalisiert" in html
    assert "Entwurf angelegt" in html


def test_das_protokoll_bietet_kein_bearbeiten_oder_loeschen(pg_session):
    """Ein Protokoll mit Knöpfen ist keins. Die Seite darf nur lesen."""
    rechnung = _rechnung(pg_session)
    app.dependency_overrides[get_db] = lambda: pg_session

    html = TestClient(app).get(f"/invoices/{rechnung.id}").text
    abschnitt = html.upper().split("ÄNDERUNGSPROTOKOLL")[1]

    for verboten in ("PROTOKOLL/LOESCHEN", "PROTOKOLL/BEARBEITEN"):
        assert verboten not in abschnitt
