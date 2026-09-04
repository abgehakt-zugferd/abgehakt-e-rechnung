"""Signierte Uebergabebelege fuer Tests, ohne die echten Vektoren.

Die Formatvektoren liegen ausserhalb des Repositoriums und sind nicht immer da
(tests/vektoren/). Was hier entsteht, ist ein eigener Probeschluessel und ein
eigener Beleg - fuer alles, was mit den Vektoren nichts zu tun hat.
"""

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


def schluesselpaar(wurzel):
    """Legt einen Probeschluessel unter `wurzel` ab und gibt (signieren, ordner)."""
    privat = Ed25519PrivateKey.generate()
    ordner = wurzel / ABSENDER_TANTIEMEN
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{SCHLUESSEL_ID}.pub").write_bytes(
        privat.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    (ordner / f"{SCHLUESSEL_ID}.json").write_text(
        json.dumps({
            "schluessel_id": SCHLUESSEL_ID,
            "absender": ABSENDER_TANTIEMEN,
            "verfahren": "Ed25519",
            "gueltig_von": "2026-09-01T00:00:00Z",
            "gueltig_bis": None,
        }),
        encoding="utf-8",
    )
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
