"""Öffentliche Schlüssel der Übergabe-Absender (§ 6 UEBERGABEFORMAT).

Parallele zu tantiemen-app/storage/schluessel.py — eigene Kopie, damit die
Signaturprüfung hier nicht die des Absenders importiert.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.serialization import load_pem_public_key

from app.installation import is_testinstanz
from app.services.protokoll import zeit

_WURZEL = Path(__file__).resolve().parents[2] / "schluessel"

# Was eine Schluesselkennung sein darf (Absender wie schluessel_id): Die beiden
# bauen den Pfad zum Schluessel, und sie kommen aus Belegfeldern - aus der
# Datei, die ein Absender hingelegt hat. Ein Wert wie "../x" oder mit "/"
# wuerde aus dem Schluesselordner hinausfuehren, und ein Wert, der keine
# Zeichenkette ist, liefe ohnehin auf einen TypeError, der den ganzen Beleg
# lahmlegte statt eines Befunds. Kleinbuchstaben genuegen: alle echten
# Kennungen (Ordner wie Schluessel) bestehen aus ihnen.
_KENNUNG = re.compile(r"^[a-z0-9][a-z0-9._-]*$")

# Ein Probeschluessel ist am NAMEN erkennbar und gilt nur in einer Testinstanz.
# Am Namen und nicht an einer Angabe im Beiblatt: das Beiblatt liegt beim
# Empfaenger und kann verrutschen, der Name steht in jedem signierten Beleg.
PROBE_KENNZEICHEN = "-probe-"

# § 6: Das Beiblatt eines oeffentlichen Schluessels hat einen geschlossenen
# Feldbestand (Formatverzeichnis, `schluessel_beiblatt`); `notizen` ist das
# einzige freie Feld, `gueltig_bis` null heisst ohne Ablauf. Unbekannte Felder,
# fehlende Pflichtfelder oder eine falsche Zeitform machen den Schluessel
# unbrauchbar: Der Tippfehler `gueltigbis` statt `gueltig_bis` galt sonst als
# Schluessel ohne Ablauf, denn get() las das Feld einfach nicht.
_BEIBLATT_PFLICHT = ("schluessel_id", "absender", "verfahren", "gueltig_von")
_BEIBLATT_ERLAUBT = _BEIBLATT_PFLICHT + ("gueltig_bis", "notizen")


class SchluesselUnbekannt(LookupError):
    """Signiert mit etwas, das hier niemand hinterlegt hat."""


class SchluesselNichtGueltig(ValueError):
    """Der Schlüssel gibt es, er galt zu diesem Zeitpunkt aber nicht."""


class ProbeschluesselImEchtlauf(SchluesselUnbekannt):
    """Ein Probeschlüssel, und diese Installation ist keine Testinstanz.

    Eine Kettenprobe darf nie den echten Bestand berühren, und ein
    Probeschlüssel, der im Echtlauf gälte, hebt genau diese Trennung auf.
    """


def schluessel_laden(
    absender: str,
    schluessel_id: str,
    erzeugt_am: datetime,
    wurzel: Optional[Path] = None,
):
    """Öffentlicher Schlüssel für den Erzeugungszeitpunkt des Belegs.

    Jedes kaputte Beiblatt wirft SchluesselUnbekannt oder SchluesselNichtGueltig
    und nie eine andere Ausnahme: Der Aufrufer lehnt den Beleg mit
    SCHLUESSEL_UNBEKANNT ab, und ein Beiblatt, das der Empfaenger nicht lesen
    kann, ist seine eigene Sache.
    """
    # Erst die Form der Kennung, dann irgendein Dateizugriff: Ein Wert, der
    # nicht wie eine Kennung aussieht, hat keinen Schluessel, bevor ueberhaupt
    # ein Pfad aufgeloest wird.
    if (not isinstance(absender, str) or _KENNUNG.match(absender) is None
            or not isinstance(schluessel_id, str) or _KENNUNG.match(schluessel_id) is None):
        raise SchluesselUnbekannt(f"{absender}/{schluessel_id}: keine Schluesselkennung")

    if PROBE_KENNZEICHEN in schluessel_id and not is_testinstanz():
        raise ProbeschluesselImEchtlauf(
            f"{schluessel_id} ist ein Probeschlüssel und gilt nur in der Testinstanz"
        )

    ordner = (Path(wurzel) if wurzel else _WURZEL).resolve()
    pem = ordner / absender / f"{schluessel_id}.pub"
    beiblatt = ordner / absender / f"{schluessel_id}.json"
    # Die Kennung allein genuegt nicht: Ein VERWEIS im Ordner (ein symlink,
    # den jemand hinterlegt hat) fuehrte trotz erlaubter Zeichen hinaus.
    # Aufgeloest muss der Pfad unterhalb der Wurzel bleiben.
    if (not pem.resolve().is_relative_to(ordner)
            or not beiblatt.resolve().is_relative_to(ordner)):
        raise SchluesselUnbekannt(
            f"{absender}/{schluessel_id}: ausserhalb des Schluesselordners"
        )
    if not pem.exists() or not beiblatt.exists():
        raise SchluesselUnbekannt(f"{absender}/{schluessel_id}")

    try:
        angaben = json.loads(beiblatt.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SchluesselUnbekannt(f"{absender}/{schluessel_id}: Beiblatt ist kein JSON")
    if not isinstance(angaben, dict):
        raise SchluesselUnbekannt(f"{absender}/{schluessel_id}: Beiblatt ist kein Objekt")
    unbekannt = sorted(set(angaben) - set(_BEIBLATT_ERLAUBT))
    if unbekannt:
        raise SchluesselUnbekannt(
            f"{absender}/{schluessel_id}: unbekanntes Feld {unbekannt[0]}"
        )
    fehlt = [name for name in _BEIBLATT_PFLICHT if name not in angaben]
    if fehlt:
        raise SchluesselUnbekannt(f"{absender}/{schluessel_id}: Pflichtfeld {fehlt[0]} fehlt")

    # Die Zeitform des § 2 gilt auch hier (protokoll.zeit, seit #163 die eine
    # Formprobe): fromisoformat haette eine naive gueltig_von anstandslos
    # geparsst, und der Vergleich mit erzeugt_am waere TypeError geworden.
    von = zeit(angaben["gueltig_von"])
    if von is None:
        raise SchluesselNichtGueltig(
            f"{absender}/{schluessel_id} nennt keine gueltig_von der Form YYYY-MM-DDTHH:MM:SSZ"
        )
    bis = None
    if angaben.get("gueltig_bis") is not None:
        bis = zeit(angaben["gueltig_bis"])
        if bis is None:
            raise SchluesselNichtGueltig(
                f"{absender}/{schluessel_id} nennt keine gueltig_bis der Form YYYY-MM-DDTHH:MM:SSZ"
            )
    if erzeugt_am < von:
        raise SchluesselNichtGueltig(
            f"{absender}/{schluessel_id} galt am {erzeugt_am.isoformat()} noch nicht"
        )
    if bis is not None and erzeugt_am >= bis:
        raise SchluesselNichtGueltig(
            f"{absender}/{schluessel_id} galt am {erzeugt_am.isoformat()} nicht mehr"
        )
    return load_pem_public_key(pem.read_bytes())
