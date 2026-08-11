"""Rechnungsliste und Archiv dürfen nicht alles auf einmal laden (09.08.2026).

Beide Seiten holten bisher den vollständigen Bestand: `query(...).all()` bzw.
`iterdir()` über das ganze Verzeichnis. Das ist unauffällig, solange man mit
Testdaten arbeitet, und wird zum Problem genau dort, wo das Programm hin soll:
acht Jahre Aufbewahrung, ein paar tausend Belege, ein alter Bürorechner.

Zwei Dinge, die dabei nicht verwechselt werden dürfen:

* **Die Zahl unten muss der Wahrheit entsprechen.** Wer nur die ersten 50 lädt
  und dann „50 Rechnungen" schreibt, hat das Problem nicht gelöst, sondern
  versteckt. Gezählt wird in der Datenbank, geladen wird die Seite.
* **Filter und Suche müssen das Blättern überleben.** Eine zweite Seite, die den
  Statusfilter vergisst, zeigt etwas anderes als die erste und ist schlimmer als
  keine zweite Seite.

Beim Archiv bleibt das Durchmustern des Verzeichnisses bestehen: „neueste zuerst"
lässt sich ohne vollständige Liste nicht beantworten. Gespart wird das Aufbauen
und Ausliefern tausender Tabellenzeilen, und der Verzeichnisdurchgang läuft über
`os.scandir`, das die Angaben aus einem Durchgang mitnimmt.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.routers.invoices import SEITENGROESSE


def teardown_function():
    app.dependency_overrides.clear()


def _rechnungen(pg_session, anzahl: int, status: str = "draft", praefix: str = "RE"):
    """Der Präfix ist ein Parameter, weil `invoice_number` eindeutig ist: zwei
    Aufrufe im selben Test kollidierten sonst und der Test wäre aus dem falschen
    Grund rot."""
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                     address_line1="Weg 1", zip_code="80331", city="München",
                     country="DE")
    pg_session.add(kunde)
    pg_session.flush()
    for i in range(anzahl):
        pg_session.add(Invoice(
            invoice_number=f"{praefix}-2026-{i:04d}", customer_id=kunde.id,
            issue_date=date(2026, 1, 1) + timedelta(days=i),
            due_date=date(2026, 2, 1) + timedelta(days=i),
            net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
            gross_total=Decimal("119.00"), status=status,
        ))
    pg_session.commit()
    return kunde


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


# ── Rechnungsliste ──────────────────────────────────────────────────────────

def test_die_liste_laedt_hoechstens_eine_seite(pg_session):
    """Sortiert wird nach Rechnungsdatum absteigend, und `_rechnungen` vergibt
    aufsteigende Daten. Auf Seite 1 stehen also die HÖCHSTEN Nummern; die
    ältesten fünf gehören auf Seite 2."""
    _rechnungen(pg_session, SEITENGROESSE + 5)

    html = _client(pg_session).get("/invoices/").text

    assert "RE-2026-0054" in html, "Die neueste fehlt auf Seite 1"
    assert "RE-2026-0000" not in html, "Die älteste steht noch auf Seite 1"


def test_die_zweite_seite_zeigt_den_rest(pg_session):
    _rechnungen(pg_session, SEITENGROESSE + 5)

    html = _client(pg_session).get("/invoices/?seite=2").text

    assert "RE-2026-0000" in html, "Die älteste fehlt auf der letzten Seite"


def test_die_gesamtzahl_wird_gezaehlt_nicht_geschaetzt(pg_session):
    """Sonst behauptet die Seite, es gäbe genau so viele wie geladen."""
    _rechnungen(pg_session, SEITENGROESSE + 5)

    html = _client(pg_session).get("/invoices/").text

    assert str(SEITENGROESSE + 5) in html


def test_das_blaettern_behaelt_den_statusfilter(pg_session):
    _rechnungen(pg_session, SEITENGROESSE + 5, status="draft")
    _rechnungen(pg_session, 3, status="issued", praefix="GS")

    html = _client(pg_session).get("/invoices/?status=draft&seite=2").text

    assert "status=draft" in html, "Der Weiter-Verweis verliert den Filter"


def test_eine_unsinnige_seitenzahl_fuehrt_nicht_zum_absturz(pg_session):
    _rechnungen(pg_session, 3)
    client = _client(pg_session)

    for wert in ("0", "-1", "99999"):
        antwort = client.get(f"/invoices/?seite={wert}")
        assert antwort.status_code == 200, wert


# ── Archiv ──────────────────────────────────────────────────────────────────

def test_das_archiv_liefert_hoechstens_eine_seite(tmp_path, monkeypatch):
    from app.routers import archive

    verzeichnis = tmp_path / "pdfs"
    verzeichnis.mkdir()
    for i in range(archive.SEITENGROESSE + 7):
        (verzeichnis / f"RE-2026-{i:04d}.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(archive.settings, "storage_path", tmp_path)

    seite = archive._dateien("pdfs")

    assert len(seite.dateien) == archive.SEITENGROESSE
    assert seite.gesamt == archive.SEITENGROESSE + 7


def test_das_archiv_zaehlt_auch_beim_suchen_richtig(tmp_path, monkeypatch):
    """Die Zahl muss sich auf die Suche beziehen, nicht auf das ganze Verzeichnis."""
    from app.routers import archive

    verzeichnis = tmp_path / "pdfs"
    verzeichnis.mkdir()
    for i in range(5):
        (verzeichnis / f"RE-2026-{i:04d}.pdf").write_bytes(b"%PDF-1.4\n")
    for i in range(3):
        (verzeichnis / f"GS-2026-{i:04d}.pdf").write_bytes(b"%PDF-1.4\n")
    monkeypatch.setattr(archive.settings, "storage_path", tmp_path)

    seite = archive._dateien("pdfs", q="GS-")

    assert seite.gesamt == 3
    assert all(d["name"].startswith("GS-") for d in seite.dateien)


def test_das_archiv_bleibt_neueste_zuerst(tmp_path, monkeypatch):
    """Die Begrenzung darf nicht die Reihenfolge kippen — sonst zeigt Seite 1
    zufällige alte Dateien statt der letzten Belege."""
    import os
    from app.routers import archive

    verzeichnis = tmp_path / "pdfs"
    verzeichnis.mkdir()
    for i in range(archive.SEITENGROESSE + 3):
        p = verzeichnis / f"RE-2026-{i:04d}.pdf"
        p.write_bytes(b"%PDF-1.4\n")
        os.utime(p, (1_700_000_000 + i * 60, 1_700_000_000 + i * 60))
    monkeypatch.setattr(archive.settings, "storage_path", tmp_path)

    seite = archive._dateien("pdfs")

    zeiten = [d["geaendert"] for d in seite.dateien]
    assert zeiten == sorted(zeiten, reverse=True)
    assert seite.dateien[0]["name"] == f"RE-2026-{archive.SEITENGROESSE + 2:04d}.pdf"
