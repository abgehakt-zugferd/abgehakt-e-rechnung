"""Erzeugt IBAN-Laengentabelle und EPC-SCT-Praefixsatz aus versionierten Artefakten.

Liegt unter app/, damit die Suite den Generator gegen den Worktree pruefen kann
(run-tests.sh mountet app/ und tests/, nicht scripts/). Das Wartungsskript
scripts/gen_iban_daten.py bleibt der CLI-Einstieg und ruft main() hier auf.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
DATA = APP / "data"
REGISTRY_ART = DATA / "iban_registry_r103.txt"
EPC_ART = DATA / "epc_sct_iban_prefixes_v8.txt"
MODUL = APP / "iban_daten.py"
TSV = DATA / "iban_laengen.tsv"

ERWARTETE_REGISTRY = 89
ERWARTETE_EPC = 42


def _payload_und_sha(pfad: Path) -> tuple[str, str, str]:
    text = pfad.read_text(encoding="utf-8")
    deklariert = ""
    for zeile in text.splitlines():
        if zeile.startswith("# Inhalt-SHA-256"):
            deklariert = zeile.rsplit(":", 1)[-1].strip()
            break
    payload = "".join(
        zeile + "\n"
        for zeile in text.splitlines()
        if zeile.strip() and not zeile.lstrip().startswith("#")
    )
    berechnet = hashlib.sha256(payload.encode()).hexdigest()
    return payload, deklariert, berechnet


def lies_registry() -> dict[str, int]:
    payload, deklariert, berechnet = _payload_und_sha(REGISTRY_ART)
    if not deklariert or deklariert != berechnet:
        raise SystemExit(
            f"Registry-Artefakt SHA drift: deklariert={deklariert!r} berechnet={berechnet!r}"
        )
    eintraege: dict[str, int] = {}
    for zeile in payload.splitlines():
        praefix, laenge = zeile.split("\t")
        eintraege[praefix] = int(laenge)
    if len(eintraege) != ERWARTETE_REGISTRY:
        raise SystemExit(
            f"erwartet {ERWARTETE_REGISTRY} Registry-Eintraege, got {len(eintraege)}"
        )
    return eintraege


def lies_epc() -> frozenset[str]:
    payload, deklariert, berechnet = _payload_und_sha(EPC_ART)
    if not deklariert or deklariert != berechnet:
        raise SystemExit(
            f"EPC-Artefakt SHA drift: deklariert={deklariert!r} berechnet={berechnet!r}"
        )
    praefixe = frozenset(zeile for zeile in payload.splitlines() if zeile)
    if len(praefixe) != ERWARTETE_EPC:
        raise SystemExit(f"erwartet {ERWARTETE_EPC} EPC-Praefixe, got {len(praefixe)}")
    return praefixe


def als_modul(laengen: dict[str, int], epc: frozenset[str]) -> str:
    laengen_zeilen = "".join(
        f'    "{p}": {n},\n' for p, n in sorted(laengen.items())
    )
    epc_zeilen = "".join(f'    "{p}",\n' for p in sorted(epc))
    return (
        '"""Generierte IBAN-Stammdaten. Nicht von Hand pflegen: '
        "scripts/gen_iban_daten.py bzw. app.iban_daten_gen.\"\"\"\n"
        "from __future__ import annotations\n"
        "\n"
        "IBAN_LAENGEN: dict[str, int] = {\n"
        f"{laengen_zeilen}"
        "}\n"
        "\n"
        "EPC_SCT_PRAEFIXE: frozenset[str] = frozenset({\n"
        f"{epc_zeilen}"
        "})\n"
    )


def als_tsv(laengen: dict[str, int]) -> str:
    kopf = (
        "# Generiert von app.iban_daten_gen. Nicht von Hand pflegen.\n"
        "# Praefix\\tLaenge (SWIFT IBAN Registry Release 103)\n"
    )
    return kopf + "".join(f"{p}\t{n}\n" for p, n in sorted(laengen.items()))


def _block_im_modul(name: str) -> str:
    quell = MODUL.read_text(encoding="utf-8")
    if name == "IBAN_LAENGEN":
        m = re.search(
            r"^IBAN_LAENGEN: dict\[str, int\] = \{\n.*?^\}\n",
            quell,
            re.S | re.M,
        )
    else:
        m = re.search(
            r"^EPC_SCT_PRAEFIXE: frozenset\[str\] = frozenset\(\{\n.*?^\}\)\n",
            quell,
            re.S | re.M,
        )
    if not m:
        raise SystemExit(f"{name} nicht in app/iban_daten.py gefunden")
    return m.group(0)


def pruefen() -> int:
    """Erzeugt erneut und vergleicht mit eingechecktem Modul und TSV. 0=gleich."""
    laengen = lies_registry()
    epc = lies_epc()
    modul = als_modul(laengen, epc)
    tsv = als_tsv(laengen)
    if not MODUL.is_file() or not TSV.is_file():
        print("fehlende generierte Datei", file=sys.stderr)
        return 1
    erwartet_laengen = _block_im_modul("IBAN_LAENGEN")
    erwartet_epc = _block_im_modul("EPC_SCT_PRAEFIXE")
    erzeugt_laengen = re.search(
        r"^IBAN_LAENGEN: dict\[str, int\] = \{\n.*?^\}\n",
        modul,
        re.S | re.M,
    )
    erzeugt_epc = re.search(
        r"^EPC_SCT_PRAEFIXE: frozenset\[str\] = frozenset\(\{\n.*?^\}\)\n",
        modul,
        re.S | re.M,
    )
    assert erzeugt_laengen and erzeugt_epc
    if (
        erzeugt_laengen.group(0) != erwartet_laengen
        or erzeugt_epc.group(0) != erwartet_epc
        or TSV.read_text(encoding="utf-8") != tsv
    ):
        print(
            "ABWEICHUNG zwischen Erzeugung und app/iban_daten.py bzw. iban_laengen.tsv",
            file=sys.stderr,
        )
        return 1
    print(f"gleich: {len(laengen)} Laengen, {len(epc)} EPC-Praefixe")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--pruefen" in args:
        return pruefen()
    laengen = lies_registry()
    epc = lies_epc()
    print(als_modul(laengen, epc), end="")
    print("---TSV---")
    print(als_tsv(laengen), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
