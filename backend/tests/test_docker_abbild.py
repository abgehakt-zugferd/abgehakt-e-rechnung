"""Betriebsabbild — Gruppe und Compose-Regeln (#64, #65).

Statische Prüfung am Dockerfile im Image; Compose-Passwörter zusätzlich in
`.githooks/wachen.sh` (Repo-Wurzel, nicht im Testcontainer).
"""
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DOCKERFILE = BACKEND / "Dockerfile"
EXTRA_GROUP_GID = 2000


def test_die_gemeinsame_gruppe_traegt_die_vereinbarte_kennung():
    """§ 8 SYSTEMLANDSCHAFT: eine Gruppenkennung (GID) fuer geteilte Belegordner."""
    inhalt = DOCKERFILE.read_text(encoding="utf-8")

    assert f"EXTRA_GROUP_GID={EXTRA_GROUP_GID}" in inhalt
    assert "EXTRA_GROUP_NAME" in inhalt
    assert "usermod" in inhalt and "--groups" in inhalt


def test_prod_laeuft_nicht_als_root():
    zeilen = DOCKERFILE.read_text(encoding="utf-8").splitlines()
    prod_user = []
    in_prod = False
    for zeile in zeilen:
        if re.match(r"\s*FROM\s+.*\s+AS\s+prod\s*$", zeile, re.IGNORECASE):
            in_prod = True
            continue
        if in_prod and re.match(r"\s*FROM\s+", zeile, re.IGNORECASE):
            break
        if in_prod and re.match(r"\s*USER\s+", zeile, re.IGNORECASE):
            prod_user.append(zeile.split()[1])

    assert prod_user and prod_user[-1] != "root"
