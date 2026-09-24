#!/usr/bin/env python3
"""Erzeugt das statische Tupel `ISO_LAENDER` fuer `app/laender.py`.

Warum ein Skript und kein Nachschlagen zur Laufzeit: Die Liste soll ins
Auslieferungsabbild, ohne dort eine Abhaengigkeit zu tragen. Dieses Skript
laeuft nur bei der Pflege der Tabelle, nie beim Start der Anwendung. Es
schreibt nichts in `laender.py`, sondern gibt den Block auf stdout aus.

Warum es ueberhaupt im Repository liegt: Eine Nachzieh-Anleitung in Prosa
laesst sich nicht pruefen. Dieses Skript schon, und zwar gegen den Stand,
der wirklich im Modul steht:

    python scripts/gen_laender_iso.py --pruefen

Der Vergleich ist die eigentliche Zusage. Weicht die Ausgabe ab, ist
entweder die Tabelle von Hand veraendert worden oder die Quelle hat sich
bewegt; beides will gesehen werden.

Quellen:
  * `pycountry.countries` fuer die Menge der gueltigen alpha-2-Codes
    (dieselben Debian-iso-codes-Daten, aus denen die Distributionen
    ISO 3166 beziehen).
  * `babel.Locale("de").territories` fuer die deutschen Namen (CLDR).

Schnitt: pycountry-Codes, die in CLDR einen deutschen Namen haben. CLDR
kennt zusaetzlich UN-M.49-Makroregionen (dreistellig) und reservierte
Pseudo-Codes (EU, QO, ZZ, XA, XB); pycountry kennt die nicht, also fallen
sie von selbst weg. Kein Filter von Hand, keine Ausnahmeliste.

**Overlay:** Wo ein Code auch in der kuratierten `LAENDER` steht, gewinnt
deren Name. CLDR sagt zu MD "Republik Moldau", die kuratierte Liste sagt
"Moldau"; ohne das Overlay wuerde das Kundenformular anders beschriften als
das Ausstellerformular, und der Drift-Test faellt. Das ist eine Regel und
keine Ausnahmeliste: Sie gilt fuer jede Ueberschneidung.

Die Reihenfolge (DE zuerst, danach alphabetisch) benutzt
`app.laender.sortierschluessel`, dieselbe Funktion, gegen die die Suite
prueft. Zwei Kopien einer Sortierregel driften auseinander.

Regenerieren, aus `backend/` heraus:

    uv run --with 'babel==2.18.0' --with 'pycountry==26.2.16' \
        python scripts/gen_laender_iso.py

Die Zahl der Eintraege folgt der Quelle. Aendert sie sich, ist das eine
bewusste Entscheidung und wird in `tests/test_laender.py` nachgezogen,
nicht umgekehrt.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import babel
import pycountry
from babel import Locale

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.laender import LAENDER, sortierschluessel  # noqa: E402

LAENDER_PY = Path(__file__).resolve().parents[1] / "app" / "laender.py"


def eintraege() -> list[tuple[str, str]]:
    namen = Locale.parse("de").territories
    kuratiert = dict(LAENDER)
    codes = {c.alpha_2 for c in pycountry.countries}
    alle = [(code, kuratiert.get(code, namen[code])) for code in codes if code in namen]
    rest = sorted((e for e in alle if e[0] != "DE"), key=lambda e: sortierschluessel(e[1]))
    return [("DE", kuratiert["DE"]), *rest]


def als_block(paare: list[tuple[str, str]]) -> str:
    zeilen = "".join(f'    ("{code}", "{name}"),\n' for code, name in paare)
    return f"ISO_LAENDER: tuple[tuple[str, str], ...] = (\n{zeilen})\n"


def im_modul() -> str:
    quelltext = LAENDER_PY.read_text(encoding="utf-8")
    treffer = re.search(r"^ISO_LAENDER: tuple\[tuple\[str, str\], \.\.\.\] = \(\n.*?^\)\n",
                        quelltext, re.S | re.M)
    if not treffer:
        raise SystemExit("ISO_LAENDER nicht in app/laender.py gefunden")
    return treffer.group(0)


def main() -> int:
    paare = eintraege()
    erzeugt = als_block(paare)
    if "--pruefen" in sys.argv:
        if erzeugt == im_modul():
            print(f"gleich: {len(paare)} Eintraege, babel {babel.__version__}, "
                  f"pycountry {pycountry.__version__}")
            return 0
        print("ABWEICHUNG zwischen erzeugter Tabelle und app/laender.py", file=sys.stderr)
        return 1
    print(f"# {len(paare)} Eintraege, babel {babel.__version__}, "
          f"pycountry {pycountry.__version__}")
    print(erzeugt, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
