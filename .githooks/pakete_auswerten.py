#!/usr/bin/env python3
"""Auswertung fuer pakete_pruefen.sh: liest den JSON-Bericht von pip-audit.

Aufruf: pakete_auswerten.py auswerten <bericht.json> <export.txt>

Ausgabe je Zeile: ANZAHL n | FUND name version id fix x | UNGEMESSEN grund.
Exit 0 heisst nur "ausgewertet"; jede Ausnahme ist Exit 2 (nicht gemessen), nie 0.
"""
import json
import sys


def auswerten(bericht):
    pakete = json.load(open(bericht))["dependencies"]
    print("ANZAHL", len(pakete))
    for p in pakete:
        name = p["name"]
        if p.get("skip_reason"):
            print("UNGEMESSEN %s uebersprungen: %s" % (name, p["skip_reason"]))
            continue
        if not isinstance(p.get("vulns"), list):
            print("UNGEMESSEN %s ohne vulns-Liste im Bericht" % name)
            continue
        for v in p["vulns"]:
            fix = ",".join(v.get("fix_versions") or []) or "keine"
            print("FUND", name, p["version"], v["id"], "fix", fix)


if __name__ == "__main__":
    try:
        if sys.argv[1] == "auswerten":
            auswerten(sys.argv[2])
        else:
            raise ValueError("unbekannter Modus " + sys.argv[1])
    except Exception as fehler:
        print("UNGEMESSEN Auswertung brach ab: %r" % (fehler,))
        sys.exit(2)
