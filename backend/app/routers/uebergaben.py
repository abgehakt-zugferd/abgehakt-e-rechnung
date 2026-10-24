"""Die Belege im Ordner ansehen und einen davon anlegen (abgehakt#22).

Zwei Wege, und der Unterschied zwischen ihnen ist der ganze Punkt:

* GET zeigt, was im Ordner liegt. Das Lesen hat KEINE Wirkung: kein Datensatz,
  kein Zustand, keine Zeile. Der Ordner wird nur gelesen; hier schreibt nie
  jemand hinein (§ 12, Archiv nach § 147 AO).
* POST legt an. Erst dieser Knopf persistiert, und er ist ein Mensch.

Ohne den Schalter (Einstellungen) gibt es beide Wege nicht - nicht bloss keinen
Menuepunkt: eine Seite, die man erreicht, wenn man die Adresse kennt, waere
kein ausgeschaltetes Merkmal.
"""

from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.branding import register_branding_globals
from app.config import get_settings
from app.darstellung import registriere_darstellungsfilter
from app.database import get_db
from app.models.app_config import AppConfig
from app.services import (
    auftragsschluessel,
    aufstellungsauftrag_wirkung,
    rechnungsauftrag_wirkung,
)
from app.services.abrechnungsauftrag_wirkung import (
    BelegSchonVerarbeitet,
    WirkungFehler,
    entwuerfe_anlegen,
)
from app.services.uebergabe_befund import Belegurteil, beleg_beurteilen
from app.services.uebergabe_eingang import (
    RICHTUNG,
    DatenbankLage,
    KopieFehler,
    kopie_aufbewahren,
)
from app.services.uebergabe_listenaufbereitung import zeilen_aus_ordner

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)
registriere_darstellungsfilter(templates)


def _schalter(db: Session) -> None:
    """Ohne Schalter gibt es diese Wege nicht."""
    cfg = db.query(AppConfig).filter(AppConfig.id == 1).first()
    if not (cfg and cfg.beleg_integration_aktiv):
        raise HTTPException(status_code=404)


def _schluesselwurzel() -> Optional[Path]:
    pfad = get_settings().schluessel_pfad
    return Path(pfad) if pfad else None


def _belegordner() -> Optional[Path]:
    wurzel = get_settings().uebergaben_ordner
    if not wurzel:
        return None
    ordner = Path(wurzel) / RICHTUNG
    return ordner if ordner.is_dir() else None


def _anlagen_ordner(ordner: Path) -> Optional[Path]:
    """§ 8b: Die Anlagen liegen neben den Belegen im Unterordner anlagen -
    der Leser geht ueber die Empfangslage denselben Weg, der Knopf braucht ihn
    fuer die Kopien."""
    pfad = ordner / "anlagen"
    return pfad if pfad.is_dir() else None


def _datei(ordner: Path, dateiname: str) -> Path:
    """Genau eine Datei aus diesem Ordner - oder gar keine.

    Der Name kommt aus der Adresszeile. Ein Pfad, der aus dem Ordner
    hinausfuehrt, ist keine Datei dieses Ordners, sondern ein Versuch.
    """
    if dateiname != Path(dateiname).name or dateiname.startswith("."):
        raise HTTPException(status_code=404)
    datei = (ordner / dateiname).resolve()
    if datei.parent != ordner.resolve() or not datei.is_file():
        raise HTTPException(status_code=404)
    return datei


def _zurueck(fehler: str) -> RedirectResponse:
    """Zur Liste zurueck, mit dem Fehlertext URL-kodiert (urlencode).

    Der Text kommt aus Meldungen der Wirkung und der Aufbewahrung und kann
    Leerzeichen, & und Umlaute tragen. Unkodiert waere das & ein zweiter
    Query-Parameter, und die Zielseite zeigte die Meldung abgeschnitten.
    """
    return RedirectResponse(
        url=f"/uebergaben?{urlencode({'fehler': fehler})}", status_code=303,
    )


def _gemeldet(meldung: str) -> RedirectResponse:
    """Zur Liste mit einer Erfolgsmeldung - dieselbe Kodierung wie beim
    Fehler, denn auch eine Belegnummer kann Sonderzeichen tragen."""
    return RedirectResponse(
        url=f"/uebergaben?{urlencode({'meldung': meldung})}", status_code=303,
    )


def _wettlauf(db: Session, urteil: Belegurteil) -> RedirectResponse:
    """Der partielle Unique-Index des Auftragsschluessels schlug beim Commit
    zu (Festlegung 19): Der Leser fragt die Lage ohne Sperre, zwei
    gleichzeitige Annahmen sehen beide 'frei'. Der Befund ist derselbe wie
    der des Lesers, kein HTTP 500; genannt wird, was der Absender
    wiedererkennt. Die Meldung fragt die eine Stelle fuer die Sperre, die
    nicht geglaubt wurde."""
    db.rollback()
    schluessel = (urteil.nutzlast or {}).get("auftragsschluessel")
    belegt_durch = (
        auftragsschluessel.dokument_zu(db, schluessel) if schluessel else None
    )
    return _zurueck(
        "AUFTRAG_SCHON_GERECHNET: Zu diesem Auftrag gibt es inzwischen "
        f"einen anderen Beleg: {belegt_durch or 'Entwurf'}."
    )


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def belegliste(request: Request, db: Session = Depends(get_db), hinweis: str = "",
               fehler: str = "", meldung: str = ""):
    _schalter(db)
    ordner = _belegordner()
    zeilen = []
    if ordner is not None:
        zeilen = zeilen_aus_ordner(
            ordner,
            db,
            schluessel_wurzel=_schluesselwurzel(),
            anlagen_ordner_fuer=_anlagen_ordner,
        )

    return templates.TemplateResponse("uebergaben/index.html", {
        "request": request,
        "ordner": str(ordner) if ordner else "",
        "zeilen": zeilen,
        "hinweis": hinweis,
        "fehler": fehler,
        "meldung": meldung,
    })


def _anlegen(
    db: Session, urteil: Belegurteil, roh: bytes, wirkung, folgeweg, *, schluesselart: bool,
) -> RedirectResponse:
    """Der gemeinsame Weg beider Anlege-Knoepfe: erst die eigene
    Aufbewahrungskopie des Belegs (§ 12), dann die Wirkung, dann committen.
    Scheitert spaeter der Commit, bleibt die Kopie liegen; sie ist byte-gleich
    mit dem Beleg und schadet niemandem.

    `schluesselart` benennt, ob die Wirkung einen Auftragsschluessel belegt
    (§ 8a, § 8b): Nur dann ist der IntegrityError der Wettlauf, sonst waere
    die Meldung erfunden.
    """
    try:
        kopie_aufbewahren(roh, urteil.beleg_sha256, richtung=RICHTUNG)
    except KopieFehler as fehler:
        return _zurueck(str(fehler))
    try:
        ergebnis = wirkung()
        db.commit()
    except BelegSchonVerarbeitet:
        db.rollback()
        return RedirectResponse(url="/uebergaben?hinweis=bereits", status_code=303)
    except WirkungFehler as fehler:
        # Alles oder nichts: was halb entstanden waere, ist damit weg.
        db.rollback()
        return _zurueck(str(fehler))
    except IntegrityError:
        if not schluesselart:
            raise
        return _wettlauf(db, urteil)
    return folgeweg(ergebnis)


@router.post("/{dateiname}/rechnung-anlegen")
def rechnung_anlegen(dateiname: str, db: Session = Depends(get_db)):
    _schalter(db)
    ordner = _belegordner()
    if ordner is None:
        raise HTTPException(status_code=404)
    datei = _datei(ordner, dateiname)

    # Noch einmal beurteilen, nicht der Ansicht glauben: zwischen dem Anzeigen
    # und dem Knopfdruck kann der Ordner ein anderer sein.
    roh = datei.read_bytes()
    urteil = beleg_beurteilen(
        roh, DatenbankLage(db), schluessel_wurzel=_schluesselwurzel(),
    )
    if not urteil.angenommen:
        return _zurueck(urteil.befund or "ABGELEHNT")

    # Beide lesbaren Arten wirken ueber denselben Knopf, aber unterschiedlich:
    # Der abrechnungsauftrag wird zu Gutschriften (§ 8), der rechnungsauftrag
    # zu einem Entwurf der Ausgangsrechnung (§ 8a). Getrennte Stellen, dieselbe
    # Zusage: alles oder nichts, committet der Aufrufer hier.
    aus_auftrag = urteil.nutzlast_art == "rechnungsauftrag"

    def wirken():
        if aus_auftrag:
            return rechnungsauftrag_wirkung.entwurf_anlegen(
                db, urteil, dateiname=datei.name,
            )
        return entwuerfe_anlegen(db, urteil, dateiname=datei.name)

    def folgen(ergebnis):
        entwurf = ergebnis if aus_auftrag else ergebnis[0]
        return RedirectResponse(url=f"/invoices/{entwurf.id}/vorschau", status_code=303)

    return _anlegen(
        db, urteil, roh, wirken, folgen, schluesselart=aus_auftrag,
    )


@router.post("/{dateiname}/aufstellung-anlegen")
def aufstellung_anlegen(dateiname: str, db: Session = Depends(get_db)):
    """§ 8b: Aus dem angenommenen aufstellungsauftrag wird der ENTWURF einer
    Abrechnungsaufstellung, deren Detailseite danach die vergebene Nummer zeigt."""
    _schalter(db)
    ordner = _belegordner()
    if ordner is None:
        raise HTTPException(status_code=404)
    datei = _datei(ordner, dateiname)

    # Noch einmal beurteilen wie beim rechnungsauftrag; die Lage sieht die
    # Anlagen, denn ohne sie waere der Beleg gar nicht angenommen.
    roh = datei.read_bytes()
    lage = DatenbankLage(db, anlagen_ordner=_anlagen_ordner(ordner))
    urteil = beleg_beurteilen(
        roh, lage, schluessel_wurzel=_schluesselwurzel(),
    )
    if not urteil.angenommen:
        return _zurueck(urteil.befund or "ABGELEHNT")
    # Die Adresse gehoert zur Art: Ein anderer Beleg hierher gepostet waere
    # eine veraltete Seite, kein Wirken - die Wirkung kennt nur diese Felder.
    if urteil.nutzlast_art != "aufstellungsauftrag":
        return _zurueck("Aus diesem Beleg entsteht keine Abrechnungsaufstellung.")

    def wirken():
        return aufstellungsauftrag_wirkung.entwurf_anlegen(
            db, urteil, anlagen_bytes=lage.anlagen_bytes, dateiname=datei.name,
        )

    def folgen(ergebnis):
        return RedirectResponse(url=f"/aufstellungen/{ergebnis.id}", status_code=303)

    return _anlegen(db, urteil, roh, wirken, folgen, schluesselart=True)
