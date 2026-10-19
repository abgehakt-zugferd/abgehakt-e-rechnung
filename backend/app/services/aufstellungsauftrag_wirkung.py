"""Aus einem angenommenen aufstellungsauftrag wird der Entwurf einer
Abrechnungsaufstellung (§ 8b, Bauschritt 7b).

Getrennt vom Lesen wie die anderen Wirkungen (rechnungsauftrag_wirkung.py ist
das Muster): Dort (uebergabe_befund.py) wird beurteilt, hier wird geschrieben,
und erst der Knopf ALS AUFSTELLUNG ANLEGEN ruft diese Stelle auf. Was
entsteht, ist ein ENTWURF - das Stellen (ausstellungsdatum, status issued)
bleibt ein Handgriff des Menschen (aufstellung_guard).

Keine Steuer, keine Steuervorgabe: Die Aufstellung ist keine Rechnung
(§ 14 UStG); die Quellensteuer ist ein Einbehalt des Auszahlers und steht
als Betrag im Beleg. Das Muster des § 8a (Festlegung 13: am Kunden muss die
Vorgabe stehen) greift hier deshalb NICHT - der Kunde hinter der partner_id
muss nur existieren.

Die Anlagen sind der Nachweis: Jede wird byte-gleich im eigenen Speicher
aufbewahrt - dieselbe Stelle wie die Belegkopie (uebergabe_eingang.py), nur
mit eigener Endung im Unterordner anlagen. Erst wenn beide Kopien geprueft
auf der Platte liegen, entstehen die Zeilen (fail closed): Eine Aufstellung
ohne eigene Anlagen waere ein Verweis auf den Ordner eines anderen.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.models.aufstellung import Aufstellung, AufstellungAnlage
from app.services import auftragsschluessel
from app.services.abrechnungsauftrag_wirkung import (
    BelegSchonVerarbeitet,
    WirkungFehler,
    _datum,
    _kunde,
)
from app.services.invoice_number import generate_next_aufstellung_number
from app.services.uebergabe_befund import Belegurteil
from app.services.uebergabe_eingang import (
    RICHTUNG,
    KopieFehler,
    kopie_aufbewahren,
    merken,
)


def entwurf_anlegen(
    db: Session,
    urteil: Belegurteil,
    *,
    anlagen_bytes: Callable[[str], Optional[bytes]],
    dateiname: Optional[str] = None,
) -> Aufstellung:
    """Legt den Entwurf samt Anlagen auf und merkt den Beleg. Committet nicht.

    Alles oder nichts wie bei den anderen Wirkungen: Entweder steht die
    Aufstellung mit beiden Anlagenzeilen und beiden geprueften Kopien, oder
    der Aufrufer rollt zurueck. `anlagen_bytes` liest die Anlage zu ihrem
    Hash - dieselbe Frage, die der Leser an die Empfangslage stellt; der
    Router reicht die Lage selbst her, damit niemand einen zweiten,
    anderen Weg erfindet.
    """
    if not urteil.angenommen:
        raise WirkungFehler("Aus einem abgelehnten Beleg entsteht nichts.")
    if urteil.bereits_verarbeitet:
        raise BelegSchonVerarbeitet(urteil.beleg_id or urteil.beleg_sha256)
    if not urteil.nutzlast:
        raise WirkungFehler("Der Beleg traegt keine Nutzlast.")

    nutzlast = urteil.nutzlast
    kunde = _kunde(db, nutzlast["kunde"]["partner_id"])

    # Erst beide Anlagen aufbewahren, dann irgendeine Zeile: Scheitert eine
    # Kopie, ist der Zustand derselbe wie vorher (fail closed). Kopien, die
    # schon stehen, bleiben stehen - sie sind byte-gleich mit den vorgelegten
    # Bytes und schaden niemandem, dasselbe Mass wie bei der Belegkopie.
    anlagen = [
        (eintrag, _anlage_aufbewahren(eintrag, anlagen_bytes))
        for eintrag in nutzlast["anlagen"]
    ]

    entwurf = _aufstellung_aus(db, nutzlast, urteil, kunde)
    db.add(entwurf)
    db.flush()
    for eintrag, roh in anlagen:
        db.add(_anlagenzeile(entwurf, eintrag, roh))

    merken(db, urteil, dateiname=dateiname)
    return entwurf


def _anlagenzeile(
    entwurf: Aufstellung, eintrag: dict, roh: bytes,
) -> AufstellungAnlage:
    """Die Zeile der Anlage: Quelle, Name, Hash und Medientyp aus dem
    Auftrag, die Groesse von den gelesen-geschriebenen Bytes - der Leser
    pruefte Hash UND Groesse der vorgelegten Bytes, hier zaehlt, was liegt."""
    return AufstellungAnlage(
        aufstellung_id=entwurf.id,
        quelle=eintrag["quelle"],
        dateiname=eintrag["dateiname"],
        sha256=eintrag["sha256"],
        groesse=len(roh),
        medientyp=eintrag["medientyp"],
    )


def _anlage_aufbewahren(eintrag: dict, anlagen_bytes) -> bytes:
    """Liest die Anlage zu ihrem Hash und bewahrt sie byte-gleich auf (§ 12).

    Gelesen wird hier noch einmal, nicht der Annahme geglaubt: Zwischen dem
    Befund und dem Knopfdruck kann der Ordner ein anderer sein. kopie_aufbewahren
    prueft den Hash der GESCHRIEBENEN Datei gegen den Eintrag - falsche Bytes
    sind KopieFehler und damit WirkungFehler, und es entsteht nichts.
    """
    roh = anlagen_bytes(eintrag["sha256"])
    if roh is None:
        raise WirkungFehler(
            f"Die Anlage {eintrag['dateiname']} fehlt: "
            f"anlagen/{eintrag['sha256']}.xlsx"
        )
    try:
        kopie_aufbewahren(
            roh, eintrag["sha256"], RICHTUNG,
            endung="xlsx", unterordner="anlagen",
        )
    except KopieFehler as fehler:
        raise WirkungFehler(str(fehler)) from fehler
    return roh


def _aufstellung_aus(
    db: Session, nutzlast: dict, urteil: Belegurteil, kunde,
) -> Aufstellung:
    """Der Entwurf aus dem Auftrag: Alles Gebundene kommt unveraendert aus der
    signierten Nutzlast, nichts wird gerundet oder geraten (die Geldform hat
    der Leser erzwungen).

    Die Nummer zaehlt im eigenen Kreis (Festlegung 18) und ohne Datum: Das
    Ausstellungsdatum steht erst beim Stellen (aufstellung_guard), das Jahr
    der Nummer nimmt den heutigen Tag - derselbe Stil wie bei der Rechnung.
    """
    umrechnung = nutzlast.get("umrechnung")
    zeitraum = nutzlast["leistungszeitraum"]
    entwurf = Aufstellung(
        nummer=generate_next_aufstellung_number(db),
        status="draft",
        customer_id=kunde.id,
        leistung_von=_datum(zeitraum["von"]),
        leistung_bis=_datum(zeitraum["bis"]),
        zahlungsnummer=nutzlast["zahlung"]["zahlungsnummer"],
        zahlungsdatum=_datum(nutzlast["zahlung"]["datum"]),
        waehrung=nutzlast["waehrung"],
        brutto=Decimal(str(nutzlast["betraege"]["brutto"])),
        quellensteuer=Decimal(str(nutzlast["betraege"]["quellensteuer"])),
        netto=Decimal(str(nutzlast["betraege"]["netto"])),
        # Bei EUR gibt es keine umrechnung (der Leser lehnt das Feld ab), bei
        # Fremdwaehrung muessen Kurs und Zahlbetrag stehen (Festlegung 21).
        kurs=Decimal(umrechnung["kurs"]) if umrechnung else None,
        zahlbetrag_eur=Decimal(umrechnung["zahlbetrag"]) if umrechnung else None,
        uebergabe_beleg_id=urteil.beleg_id,
        uebergabe_beleg_sha256=urteil.beleg_sha256,
    )
    auftragsschluessel.belegen(entwurf, nutzlast["auftragsschluessel"])
    return entwurf
