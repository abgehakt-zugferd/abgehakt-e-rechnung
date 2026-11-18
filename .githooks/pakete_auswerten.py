#!/usr/bin/env python3
"""Auswertung fuer pakete_pruefen.sh: liest den JSON-Bericht von pip-audit.

Aufruf: pakete_auswerten.py auswerten <bericht.json> <export.txt>

Ausgabe je Zeile: ANZAHL n | FUND name version id fix x | UNGEMESSEN grund.
Exit 0 heisst nur "ausgewertet"; jede Ausnahme ist Exit 2 (nicht gemessen), nie 0.
"""
import json
import re
import sys


def norm(name):
    """Namensform nach PEP 503: klein, Folgen von - _ . werden ein -."""
    return re.sub(r"[-_.]+", "-", name).lower()


def pins(export):
    """Die Pins des Exports: normierter Name -> Name, wie er im Export steht."""
    gefunden = {}
    for zeile in open(export):
        m = re.match(r"([A-Za-z0-9][A-Za-z0-9._-]*)==", zeile)
        if m:
            gefunden[norm(m.group(1))] = m.group(1)
    return gefunden


def auswerten(bericht, export):
    pakete = json.load(open(bericht))["dependencies"]
    print("ANZAHL", len(pakete))
    erwartet = pins(export)
    gesehen = {}
    for p in pakete:
        name = p["name"]
        gesehen[norm(name)] = name
        if p.get("skip_reason"):
            print("UNGEMESSEN %s uebersprungen: %s" % (name, p["skip_reason"]))
            continue
        if not isinstance(p.get("vulns"), list):
            print("UNGEMESSEN %s ohne vulns-Liste im Bericht" % name)
            continue
        for v in p["vulns"]:
            fix = ",".join(v.get("fix_versions") or []) or "keine"
            print("FUND", name, p["version"], v["id"], "fix", fix)
    for n in sorted(set(erwartet) - set(gesehen)):
        print("UNGEMESSEN %s fehlt im Bericht" % erwartet[n])
    for n in sorted(set(gesehen) - set(erwartet)):
        print("UNGEMESSEN %s nicht im Export" % gesehen[n])


if __name__ == "__main__":
    try:
        if sys.argv[1] == "auswerten":
            auswerten(sys.argv[2], sys.argv[3])
        else:
            raise ValueError("unbekannter Modus " + sys.argv[1])
    except Exception as fehler:
        print("UNGEMESSEN Auswertung brach ab: %r" % (fehler,))
        sys.exit(2)
