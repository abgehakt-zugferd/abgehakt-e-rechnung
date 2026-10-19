"""Finalisieren der Abrechnungsaufstellung (§ 8b, Bauschritt 7c).

Muster ist das Finalisieren der Rechnung (services/rechnung/finalisieren.py): erst das
Archiv, dann der Commit — scheitert ein Schritt, liegt nichts im Archiv
und der Entwurf bleibt Entwurf. KEIN Mustang, KEINE XML: Die Aufstellung
ist keine Rechnung, PDF/A-3 ist die Ablageform.
"""
import re
from datetime import date, datetime, timezone

import pytest

import app.zeit
from app.config import get_settings
from app.services import pdfa
from app.services.aufstellung_finalisieren import FinalisierenFehler, finalisieren
from app.services.aufstellung_guard import (
    AufstellungStateError,
    register_aufstellung_guard,
)
from app.models.aufstellung import Aufstellung
from tests.factories_aufstellung import speichere_aufstellung
from tests.helpers.pdf import xmp

register_aufstellung_guard()  # idempotent — der Guard gilt auch fuer dieses Modul

# 03:30 UTC ist 05:30 Berlin (Sommerzeit) — beides derselbe Kalendertag,
# aber nur die Berlin-Zeit darf zaehlen (app.zeit).
_STELLZEIT = datetime(2026, 10, 18, 3, 30, tzinfo=timezone.utc)
STELLTAG = date(2026, 10, 18)


@pytest.fixture(autouse=True)
def heutiger_tag(monkeypatch):
    monkeypatch.setattr(app.zeit, "_utc_jetzt", lambda: _STELLZEIT)


def _frisch(pg_session, a):
    pg_session.expire_all()
    return pg_session.query(Aufstellung).filter(Aufstellung.id == a.id).one()


@pytest.mark.skipif(not pdfa.gs_available(), reason="Ghostscript nicht verfügbar")
def test_finalisieren_stellt_datum_status_datei_frist(pg_session):
    a = speichere_aufstellung(pg_session)
    finalisieren(pg_session, a, get_settings())

    frisch = _frisch(pg_session, a)
    assert frisch.status == "issued"
    assert frisch.ausstellungsdatum == STELLTAG
    assert frisch.pdf_filename == f"{a.nummer}.pdf"
    # § 147 AO: Jahresende des Ausstellungsjahres plus acht Jahre.
    assert frisch.archive_until == date(2034, 12, 31)
    assert (get_settings().storage_path / "aufstellungen" / f"{a.nummer}.pdf").exists()


@pytest.mark.skipif(not pdfa.gs_available(), reason="Ghostscript nicht verfügbar")
def test_das_archivierte_pdf_ist_pdfa(pg_session):
    """Ghostscript laeuft im Finalisieren; das Ergebnis deklariert PDF/A-3
    im XMP (pdfaid:part) — dasselbe Feld, das ein Pruefer liest."""
    a = speichere_aufstellung(pg_session)
    finalisieren(pg_session, a, get_settings())

    pfad = get_settings().storage_path / "aufstellungen" / f"{a.nummer}.pdf"
    assert pfad.read_bytes().startswith(b"%PDF")
    # Ghostscript schreibt pdfaid:part als XMP-Attribut (pdfaid:part='3').
    assert re.search(r"pdfaid:part\s*=\s*['\"]3['\"]", xmp(pfad)), \
        "XMP deklariert keinen PDF/A-Teil 3"


def test_pdfa_fehler_hinterlaesst_nichts(pg_session, monkeypatch):
    """Fail closed: Ohne PDF/A wird nicht gestellt — nichts im Archiv,
    der Datensatz bleibt draft (Festlegung: keine halben Zustaende)."""
    a = speichere_aufstellung(pg_session)
    monkeypatch.setattr(pdfa, "to_pdfa3", lambda *args, **kw: False)

    with pytest.raises(FinalisierenFehler):
        finalisieren(pg_session, a, get_settings())

    frisch = _frisch(pg_session, a)
    assert frisch.status == "draft"
    assert frisch.ausstellungsdatum is None
    assert frisch.pdf_filename is None
    assert frisch.archive_until is None
    # Das gemeinsame Wegwerf-Archiv der Session enthaelt Dateien anderer
    # Tests; zaehlt ist nur, dass DIESE Aufstellung nichts hinterlaesst.
    archiv = get_settings().storage_path / "aufstellungen"
    assert not (archiv / f"{a.nummer}.pdf").exists()
    # Auch das Wegwerf-Verzeichnis ist leer: keine Zwischenstufe bleibt liegen.
    temp = get_settings().storage_path / "temp"
    reste = [p for p in temp.iterdir()] if temp.exists() else []
    assert not any(p.name.startswith("aufstellung-finalisieren-") for p in reste)


def test_nur_entwuerfe_werden_gestellt(pg_session):
    """Verworfen ist kein Stellen: discarded erklärt die Nummernlücke
    (Festlegung 18) und bleibt ohne PDF."""
    a = speichere_aufstellung(pg_session, status="discarded")
    with pytest.raises(FinalisierenFehler):
        finalisieren(pg_session, a, get_settings())

    assert _frisch(pg_session, a).status == "discarded"


@pytest.mark.skipif(not pdfa.gs_available(), reason="Ghostscript nicht verfügbar")
def test_zweites_finalisieren_wird_abgelehnt(pg_session):
    a = speichere_aufstellung(pg_session)
    finalisieren(pg_session, a, get_settings())

    with pytest.raises(FinalisierenFehler):
        finalisieren(pg_session, a, get_settings())


@pytest.mark.skipif(not pdfa.gs_available(), reason="Ghostscript nicht verfügbar")
def test_guard_verbietet_aenderungen_nach_issued(pg_session):
    """Nach dem Stellen ist die Aufstellung inhaltlich unveraenderlich
    (GoBD, aufstellung_guard) — der Weg dorthin ist das Finalisieren."""
    a = speichere_aufstellung(pg_session)
    finalisieren(pg_session, a, get_settings())

    a.brutto = a.brutto + 1
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()
