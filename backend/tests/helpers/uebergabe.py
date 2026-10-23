"""Signierte Uebergabebelege fuer Tests, ohne die echten Vektoren.

Die Formatvektoren liegen ausserhalb des Repositoriums und sind nicht immer da
(tests/vektoren/). Was hier entsteht, ist ein eigener Probeschluessel und ein
eigener Beleg - fuer alles, was mit den Vektoren nichts zu tun hat.
"""

import hashlib
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services.uebergabebeleg import (
    ABSENDER_TANTIEMEN,
    EMPFAENGER_ABGEHAKT,
    umschlag,
)

PARTNER_A = "3f5b1c80-0000-4000-8000-00000000000a"
PARTNER_B = "3f5b1c80-0000-4000-8000-00000000000b"
SCHLUESSEL_ID = "tantiemen-2026-09"
ERZEUGT = "2026-09-03T11:00:00Z"


def beiblatt(**aenderungen):
    """Das Beiblatt des Probeschluessels, wie es das Formatverzeichnis unter
    `schluessel_beiblatt` fuehrt (§ 6): geschlossener Feldbestand, `notizen`
    als Objekt und einziges freies Feld, `gueltig_bis` Pflicht und null heisst
    ohne Ablauf."""
    angaben = {
        "schluessel_id": SCHLUESSEL_ID,
        "absender": ABSENDER_TANTIEMEN,
        "verfahren": "Ed25519",
        "gueltig_von": "2026-09-01T00:00:00Z",
        "gueltig_bis": None,
    }
    angaben.update(aenderungen)
    return angaben


def beiblatt_ablegen(wurzel, angaben):
    """Legt ein Beiblatt ab, wie es der Empfaenger vorfindet."""
    ordner = wurzel / ABSENDER_TANTIEMEN
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{SCHLUESSEL_ID}.json").write_text(
        json.dumps(angaben), encoding="utf-8",
    )


def schluesselpaar(wurzel):
    """Legt einen Probeschluessel unter `wurzel` ab und gibt (signieren, ordner)."""
    privat = Ed25519PrivateKey.generate()
    ordner = wurzel / ABSENDER_TANTIEMEN
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{SCHLUESSEL_ID}.pub").write_bytes(
        privat.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    beiblatt_ablegen(wurzel, beiblatt())
    return privat.sign, wurzel


def gutschrift(partner_id=PARTNER_A, netto="174.33", name="Autorin A"):
    return {
        "beteiligter": {"partner_id": partner_id, "anzeigename": name},
        "typcode": "389",
        "leistungszeitraum": {"von": "2026-04-01", "bis": "2026-06-30"},
        "positionen": [{
            "nr": 1,
            "bezeichnung": "Beteiligung am Deckungsbeitrag 2026-Q2, Probeverlag",
            "herleitung": {"basis_netto": "697.30", "satz": "25.00"},
            "netto": netto,
        }],
        "summe": {"netto": netto},
    }


def auftrag(**aenderungen):
    nutzlast = {
        "abrechnungsquartal": "2026-Q2",
        "projekt": {"id": "probe", "name": "Probeverlag"},
        "bemessung": {
            "erloes_netto": "797.30",
            "direktkosten_netto": "100.00",
            "deckungsbeitrag_netto": "697.30",
        },
        "grundlagen": [{
            "belegnummer": "90145",
            "beleg_sha256": "9edc0b19fcde7cc2d1aa0d46cd8412dc405660176e0065a28e983a0179dc61da",
            "leistungsperiode": "2026-04",
            "erloes_netto": "28.00",
        }],
        "gutschriften": [gutschrift()],
        "vortraege": [],
    }
    nutzlast.update(aenderungen)
    return nutzlast


def rechnungsauftrag(**aenderungen):
    """§ 8a (Fassung 1.7): Ausgangsrechnung 380 an einen Kunden, nur netto,
    je Marktplatz und Verkaufsmonat eine. Erfundene Zahlen; die negative
    Position bleibt, denn negative Positionen sind erlaubt."""
    nutzlast = {
        "auftragsschluessel": "plattform:2026-02:kanal-a:x1",
        "kunde": {"partner_id": PARTNER_A, "anzeigename": "Plattform Beispiel GmbH"},
        "typcode": "380",
        "leistungszeitraum": {"von": "2026-02-01", "bis": "2026-02-28"},
        "waehrung": "EUR",
        "positionen": [
            {"nr": 1, "gruppe": "Gruppe A", "bezeichnung": "Nutzungsrechte A", "netto": "174.44"},
            {"nr": 2, "gruppe": "Gruppe B", "bezeichnung": "Nutzungsrechte B", "netto": "-3.10"},
        ],
        "summe": {"netto": "171.34"},
        "grundlagen": [{
            "quelle": "abrechnungsbericht",
            "beleg_sha256": "1a" * 32,
            "leistungsperiode": "2026-02",
            "netto": "171.34",
        }],
    }
    nutzlast.update(aenderungen)
    return nutzlast


# § 8b: Die Anlage liegt als Datei neben dem Beleg, ihr Eintrag nennt Hash und
# Groesse derselben Bytes. Damit Tests ohne Dateisystem auskommen, stehen hier
# zwei erfundene Anlagen als Bytes; die Empfangslage eines Tests reicht sie
# nach ihrem Hash her (Empfangslage.anlagen_bytes).
ANLAGE_ABRECHNUNGSBERICHT = b"Probe-Abrechnungsbericht, erfundene Bytes ohne xlsx."
ANLAGE_ZAHLUNGSBERICHT = b"Probe-Zahlungsbericht, erfundene Bytes ohne xlsx."

ANLAGE_MEDIENTYP = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def anlage(quelle, dateiname, bytes_):
    """Ein Anlageneintrag (§ 8b) zu gegebenen Bytes: Hash und Groesse passen,
    denn beide nannte sonst schon der Lesertest."""
    return {
        "quelle": quelle,
        "dateiname": dateiname,
        "sha256": hashlib.sha256(bytes_).hexdigest(),
        "groesse": len(bytes_),
        "medientyp": ANLAGE_MEDIENTYP,
    }


def probe_anlagen() -> dict:
    """Die beiden Probeanlagen als {sha256: bytes} - der Bestand, den die
    Empfangslage eines Tests hinterlegt hat."""
    return {hashlib.sha256(b).hexdigest(): b
            for b in (ANLAGE_ABRECHNUNGSBERICHT, ANLAGE_ZAHLUNGSBERICHT)}


def anlagen_ablegen(ordner, nutzlast):
    """Legt die Anlagen eines aufstellungsauftrags als anlagen/<sha256>.xlsx
    in den Uebergabeordner, wie der Absender sie vor dem Beleg ablegt (§ 8b).
    Die Bytes kommen aus probe_anlagen - derselbe Bestand, den die
    Empfangslage eines Tests hinterlegt hat."""
    bestand = probe_anlagen()
    anlagen = ordner / "anlagen"
    anlagen.mkdir(parents=True, exist_ok=True)
    for eintrag in nutzlast["anlagen"]:
        (anlagen / f"{eintrag['sha256']}.xlsx").write_bytes(
            bestand[eintrag["sha256"]]
        )


def aufstellungsauftrag(**aenderungen):
    """§ 8b (Fassung 1.7): Abrechnungsaufstellung bei Drittlandzahlung - keine
    Rechnung, kein typcode, keine Steuerfelder, zwei Anlagen neben dem Beleg.
    Erfundene Zahlen; USD, damit die umrechnung dasteht. netto x kurs muss
    zahlbetrag NICHT ergeben: Die Plattform rechnet die Umrechnung."""
    nutzlast = {
        "auftragsschluessel": "plattform:2026-02:kanal-b:x1",
        "kunde": {"partner_id": PARTNER_A, "anzeigename": "Beispiel Services LLC"},
        "leistungszeitraum": {"von": "2026-02-01", "bis": "2026-02-28"},
        "zahlung": {"zahlungsnummer": "100000000000001", "datum": "2026-04-29"},
        "waehrung": "USD",
        "betraege": {"brutto": "6.92", "quellensteuer": "2.08", "netto": "4.84"},
        "umrechnung": {"kurs": "0.8533", "waehrung": "EUR", "zahlbetrag": "4.13"},
        "anlagen": [
            anlage("abrechnungsbericht", "bericht.xlsx", ANLAGE_ABRECHNUNGSBERICHT),
            anlage("zahlungsbericht", "zahlung.xlsx", ANLAGE_ZAHLUNGSBERICHT),
        ],
    }
    nutzlast.update(aenderungen)
    return nutzlast


def beleg(signieren, nutzlast=None, **aenderungen) -> bytes:
    felder = dict(
        nutzlast=auftrag() if nutzlast is None else nutzlast,
        nutzlast_art="abrechnungsauftrag",
        beleg_id="11111111-2222-4333-8444-555555555555",
        erzeugt_am=ERZEUGT,
        absender=ABSENDER_TANTIEMEN,
        empfaenger=EMPFAENGER_ABGEHAKT,
        vorgaenger_hash=None,
        schluessel_id=SCHLUESSEL_ID,
        signierer=signieren,
    )
    felder.update(aenderungen)
    return umschlag(**felder)
