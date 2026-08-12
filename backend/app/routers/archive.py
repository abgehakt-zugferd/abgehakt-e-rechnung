"""Archiv-Ansicht (#148): die abgelegten E-Rechnungen einsehen und herunterladen.

Warum in der App statt „Ordner öffnen": Browser navigieren von einer `http://`-Seite
nicht auf `file://`, ein Knopf zum Finder ist also nicht baubar — und der Container
kennt den Host-Pfad gar nicht, er sieht nur sein gemountetes `/app/storage`.

Sichtbar sind ausschließlich `pdfs/` und `xml/`. `temp/` (Vorschau-Reste,
Zwischendateien) und `imports/` (fremde Uploads) sind kein Archiv.
"""
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.branding import register_branding_globals
from app.darstellung import registriere_darstellungsfilter
from app.config import get_settings

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)

settings = get_settings()

# Schlüssel = Verzeichnisname unter storage/ UND Wert des URL-Segments `bereich`.
# Was hier nicht steht, ist über die Route nicht erreichbar.
BEREICHE: dict[str, str] = {"pdfs": "PDF", "xml": "XML"}


# Wie viele Dateien eine Seite zeigt. Siehe `SEITENGROESSE` in `routers/invoices.py`:
# bewusst eine Konstante, keine Einstellung.
SEITENGROESSE = 100


@dataclass
class Dateiseite:
    dateien: list[dict]
    gesamt: int
    seite: int
    seiten: int


def _dateien(bereich: str, q: str = "", seite: int = 1) -> Dateiseite:
    """Eine Seite des Archivbereichs, neueste zuerst.

    Das Durchmustern des Verzeichnisses bleibt: „neueste zuerst" lässt sich ohne
    die vollständige Liste nicht beantworten, und ein Dateisystem führt keinen
    Index nach Änderungszeit. Gespart wird das, was wirklich teuer ist — das
    Aufbauen und Ausliefern tausender Tabellenzeilen.

    `os.scandir` statt `Path.iterdir`: es nimmt Typ und Angaben aus demselben
    Verzeichnisdurchgang mit, statt für jede Datei erneut nachzufragen. Bei
    zehntausend Belegen ist das der Unterschied zwischen einem und zehntausend
    zusätzlichen Zugriffen.
    """
    verzeichnis = settings.storage_path / bereich
    if not verzeichnis.is_dir():
        return Dateiseite([], 0, 1, 1)
    suche = q.strip().lower()
    treffer = []
    with os.scandir(verzeichnis) as eintraege:
        for eintrag in eintraege:
            if suche and suche not in eintrag.name.lower():
                continue
            if not eintrag.is_file():
                continue
            stat = eintrag.stat()
            treffer.append({
                "name": eintrag.name,
                "groesse": stat.st_size,
                "geaendert": datetime.fromtimestamp(stat.st_mtime),
            })
    treffer.sort(key=lambda d: d["geaendert"], reverse=True)

    gesamt = len(treffer)
    seiten = max(1, -(-gesamt // SEITENGROESSE))
    seite = min(max(seite, 1), seiten)
    beginn = (seite - 1) * SEITENGROESSE
    return Dateiseite(treffer[beginn:beginn + SEITENGROESSE], gesamt, seite, seiten)


@router.get("/archiv", response_class=HTMLResponse)
def archive_page(request: Request, q: str = "", seite: int = 1):
    return templates.TemplateResponse("archive/index.html", {
        "request": request,
        "q": q,
        "bereiche": [
            {"schluessel": schluessel, "titel": titel,
             "seite": _dateien(schluessel, q, seite)}
            for schluessel, titel in BEREICHE.items()
        ],
    })


@router.get("/archiv/datei/{bereich}/{name}")
def archive_file(bereich: str, name: str):
    """Einzelne Archivdatei ausliefern.

    Der Dateiname kommt aus der URL — ohne Eingrenzung wäre das ein Leseloch in den
    ganzen Container. Zwei Schranken: `Path(name).name` wirft jede Pfadangabe weg,
    und der aufgelöste Pfad muss danach WIRKLICH im Zielverzeichnis liegen (fängt
    auch einen Symlink nach draußen).
    """
    if bereich not in BEREICHE:
        raise HTTPException(404, "Unbekannter Archivbereich.")
    basis = (settings.storage_path / bereich).resolve()
    ziel = (basis / Path(name).name).resolve()
    if ziel.parent != basis or not ziel.is_file():
        raise HTTPException(404, "Datei nicht gefunden.")
    return FileResponse(str(ziel), filename=ziel.name)
