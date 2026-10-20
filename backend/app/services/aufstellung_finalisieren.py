"""Stellt die Abrechnungsaufstellung: PDF erzeugen, PDF/A heben, archivieren.

Muster ist das Finalisieren der Rechnung (services/rechnung/finalisieren.py, Bauschritt 4):
Das PDF entsteht in einem Wegwerf-Verzeichnis UNTER dem storage-Mount, wird
mit Ghostscript auf PDF/A-3 gehoben und mit os.replace veroeffentlicht —
erst DANN wird committet. Scheitert ein Schritt, liegt nichts im Archiv und
der Datensatz bleibt draft (fail closed): Ein Beleg ohne Zeile loest sich
durch erneutes Finalisieren auf, eine gestellte Zeile ohne Beleg waere
unveraenderlich und kaputt.

KEIN Mustang, KEINE XML (Entscheidung 8): Die Aufstellung ist keine
Rechnung, PDF/A-3 ist die Ablageform — darum auch keine Validierung durch
Mustang, nur der Erfolg des Ghostscript-Laufs.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.aufstellung import Aufstellung
from app.models.company import Company
from app.services import aufstellung_pdf, pdfa
from app.services.aufstellung_storno import original_aufheben
from app.services.archive_frist import berechne_archive_until
from app.services.rechnung.firma import eingerichtete_firma
from app.zeit import heute


class FinalisierenFehler(RuntimeError):
    """Das Stellen schlug fehl — der Entwurf bleibt Entwurf."""


def finalisieren(db: Session, aufstellung: Aufstellung, settings) -> Aufstellung:
    """draft → issued: Ausstellungsdatum heute (Europe/Berlin), PDF/A-3 im
    Archiv unter storage/aufstellungen/, archive_until nach § 147 AO.

    Committet selbst; bei jedem Fehlschlag rollt die Session zurueck, und
    der Aufrufer sieht einen FinalisierenFehler mit Meldung.
    """
    if aufstellung.status != "draft":
        raise FinalisierenFehler(
            "Nur ein Entwurf kann gestellt werden — die Aufstellung ist "
            f"bereits '{aufstellung.status}'."
        )
    company = _firma(db)
    stelltag = heute()
    arbeitsverzeichnis = Path(tempfile.mkdtemp(
        prefix=f"aufstellung-finalisieren-{aufstellung.nummer}-",
        dir=_arbeitswurzel(settings),
    ))
    try:
        # Das Datum gehoert auf das PDF (Kopfzeile) und ist zugleich die
        # Pflicht des Uebergangs (Guard): Es steht deshalb VOR der Erzeugung
        # am Objekt — im Fehlschlagfall nimmt der Rollback es zurueck.
        aufstellung.ausstellungsdatum = stelltag
        ziel = _archivieren(aufstellung, company, arbeitsverzeichnis, settings)
        aufstellung.pdf_filename = ziel.name
        aufstellung.archive_until = berechne_archive_until(stelltag)
        aufstellung.status = "issued"
        try:
            # Kein Autoflush zwischen Storno und Original: Der Guard prueft
            # beide Seiten gemeinsam; erst das archivierte Storno gibt frei.
            with db.no_autoflush:
                original_aufheben(db, aufstellung)
            db.commit()
        except Exception:
            # Erst Archiv, dann Commit — scheitert der Commit, wird das eben
            # Veroeffentlichte wieder eingesammelt (Muster Rechnung).
            ziel.unlink(missing_ok=True)
            db.rollback()
            raise
    except Exception:
        # Jeder Fehlschlag (PDF, PDF/A, Veroeffentlichen, Commit) darf kein
        # halbes Objekt im Speicher hinterlassen: Der Rollback stellt den
        # draft wieder her, wie er in der DB steht.
        db.rollback()
        raise
    finally:
        shutil.rmtree(arbeitsverzeichnis, ignore_errors=True)
    return aufstellung


def _archivieren(aufstellung, company, arbeitsverzeichnis: Path, settings) -> Path:
    """Sichtbares PDF erzeugen, auf PDF/A-3 heben, veroeffentlichen.

    Wirft FinalisierenFehler, wenn Ghostscript fehlt oder scheitert — dann
    liegt noch nichts im Archiv (fail closed: Ohne PDF/A wird nicht gestellt).
    """
    sichtbar = arbeitsverzeichnis / f"{aufstellung.nummer}_sichtbar.pdf"
    aufstellung_pdf.erzeuge_pdf(aufstellung, company, sichtbar)
    archivfaehig = arbeitsverzeichnis / f"{aufstellung.nummer}.pdf"
    if not pdfa.gs_available() or not pdfa.to_pdfa3(
        sichtbar, archivfaehig, title=aufstellung.nummer,
    ):
        raise FinalisierenFehler(
            "PDF/A konnte nicht erzeugt werden (Ghostscript fehlt oder "
            "scheiterte). Die Aufstellung bleibt Entwurf — bitte erneut "
            "finalisieren."
        )
    return _veroeffentliche(archivfaehig, settings)


def _firma(db: Session) -> Company:
    """Die ausstellende Firma. Ohne eingerichtete Firma gibt es keinen
    Aussteller - derselbe Torhueter wie bei der Rechnung (get_company),
    nur als FinalisierenFehler statt HTTPException, weil hier kein HTTP
    im Spiel ist."""
    company = eingerichtete_firma(db)
    if company is None:
        raise FinalisierenFehler(
            "Firmendaten nicht konfiguriert. Bitte zuerst die Ersteinrichtung "
            "abschließen."
        )
    return company


def _arbeitswurzel(settings) -> Path:
    """Wegwerf-Wurzel UNTER dem storage-Mount (Muster Rechnung, #12/#13):
    Das Veroeffentlichen ist ein os.replace und nur innerhalb desselben
    Dateisystems atomar — das Temp-Verzeichnis des Betriebssystems kann
    auf einem anderen Mount liegen. storage/temp/ ist ausserdem aus der
    Archivansicht ausgenommen."""
    wurzel = Path(settings.storage_path) / "temp"
    wurzel.mkdir(parents=True, exist_ok=True)
    return wurzel


def _veroeffentliche(quelle: Path, settings) -> Path:
    """PDF/A aus dem Arbeitsverzeichnis ins Archiv uebernehmen.

    os.replace statt Kopieren: atomar innerhalb des Dateisystems, im
    Archiv liegt nie eine halb geschriebene Datei. Das Zielverzeichnis
    heisst aufstellungen/ — eigene Abteilung, denn die Aufstellung ist
    KEINE Rechnung und liegt nicht zwischen den Rechnungs-PDFs."""
    ziel = Path(settings.storage_path) / "aufstellungen" / quelle.name
    ziel.parent.mkdir(parents=True, exist_ok=True)
    os.replace(quelle, ziel)
    return ziel
