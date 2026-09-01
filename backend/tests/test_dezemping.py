"""Kein fremder Firmenname irgendwo im Repo (#99 §4, Leitplanke L4).

Das ist kein Kosmetiktest: dieses Repo ist öffentlich, und die Nutzerin ist
eine fremde Kanzlei. Was hier durchrutscht, steht anschließend in ihrer
Oberfläche, in ihrem Rechnungs-PDF oder in einer Mail an ihren Steuerberater.

Dieser Wächter ist strenger als der im Quell-Repo. Dort galten drei bewusste
Einschränkungen, die hier alle hinfällig sind:
- `backend/tests/` war ausgenommen („Fixtures werden nicht ausgeliefert") —
  hier wird das ganze Repo ausgeliefert, Fixtures eingeschlossen.
- Infrastrukturnamen (DB-Name, Rollen) durften bleiben, weil ihre Umbenennung
  eine Migration in einer laufenden Produktionsdatenbank gewesen wäre — hier
  gibt es keine Bestandsdatenbank.
- `app/db/roles.py` war ausgenommen (Bootstrap-User `zemp`, OID 10) — die
  Rollen heißen hier von Anfang an `abgehakt_*`.

⚠️ Der Wächter läuft im Container und sieht deshalb nur den Backend-Baum.
`docker-compose.yml`, `.env.example`, `.github/` und `docs/` liegen dort
nicht — ein grüner Lauf ist kein Freibrief für den Push. Diese Dateien deckt
der repo-weite `grep` in der Abnahme ab.
"""
import re
from pathlib import Path

import pytest

from app import branding

WURZEL = Path(".")

VERBOTEN = re.compile(r"ZEMP|Golden Goose|Salachweg|Buchloe|zemp|saleshero", re.IGNORECASE)

_IGNORIEREN = ("__pycache__", "storage/", "lib/", ".pytest_cache", ".ruff_cache")

# Technische Gruppenkennung (GID 2000) — kein Firmenname in der Oberflaeche.
_DOCKERFILE = Path("Dockerfile")

# Diese Datei nennt die verbotenen Wörter selbst — sie ist die Liste. Seit der
# Suchraum das ganze Repo umfasst (statt nur `app/`), fände sie sich sonst selbst
# und wäre nie grün zu bekommen.
_SELBST = Path("tests/test_dezemping.py")


def _treffer(pfad: Path) -> list[str]:
    zeilen = pfad.read_text(encoding="utf-8").splitlines()
    return [f"{pfad}:{i}: {z.strip()[:100]}"
            for i, z in enumerate(zeilen, 1) if VERBOTEN.search(z)]


def _dateien(muster: str) -> list[Path]:
    return sorted(p for p in WURZEL.rglob(muster)
                  if p != _SELBST and p != _DOCKERFILE
                  and not any(x in str(p) for x in _IGNORIEREN))


@pytest.mark.parametrize("muster", ["*.html", "*.py", "*.sh", "*.ini", "*.toml", "*.md"])
def test_kein_fremder_firmenname(muster):
    treffer = [t for p in _dateien(muster) for t in _treffer(p)]

    assert not treffer, "Fremder Firmenname im Repo:\n" + "\n".join(treffer)


def test_produktname_ist_gesetzt():
    """`branding.py` trug den Platzhalter `<PRODUKTNAME>` — der stünde sonst im
    Footer jeder Seite."""
    assert branding.PRODUCT_NAME == "Abgehakt"
    assert "<" not in branding.PRODUCT_NAME
