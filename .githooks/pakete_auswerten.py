#!/usr/bin/env python3
"""Auswertung fuer pakete_pruefen.sh: liest den JSON-Bericht von pip-audit.

Aufruf: pakete_auswerten.py auswerten <bericht.json> <export.txt>
        pakete_auswerten.py ausnahmen <datei> <heute JJJJ-MM-TT>

Ausgabe je Zeile: ANZAHL n | FUND name version id fix x | UNGEMESSEN grund.
Exit 0 heisst nur "ausgewertet"; jede Ausnahme ist Exit 2 (nicht gemessen), nie 0.
"""
import datetime
import json
import re
import sys


# Hoechstfrist einer Ausnahme in Tagen, gerechnet ab `seit` (nicht ab heute: sonst
# wanderte die Frist mit jedem Lauf mit und alterte nie). Dieselbe Zahl wie im Plugin.
HOECHSTFRIST_TAGE = 30


def tag(text):
    """Ein echter Kalendertag JJJJ-MM-TT, sonst ValueError. 2026-02-31 ist keiner."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError("Datum '%s' ist nicht JJJJ-MM-TT" % text)
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ValueError("Datum %s ist kein Kalendertag" % text)


def pruefe_ausnahme(nr, felder, heute):
    """Gibt die Fehlermeldung zurueck oder None, wenn die Ausnahme gilt."""
    if len(felder) != 4:
        return ("Ausnahme unvollständig (Zeile %d): erwartet 'Kennung Issue Ablauf seit', "
                "gefunden: %s" % (nr, " ".join(felder)))
    kennung, issue, ablauf, seit = felder
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", kennung):
        return "Ausnahme Zeile %d: Kennung '%s' ist keine gueltige Kennung." % (nr, kennung)
    if not re.fullmatch(r"#?\d+", issue):
        return "Ausnahme Zeile %d (%s): Issue '%s' ist keine Nummer (z. B. #123)." % (nr, kennung, issue)
    try:
        bis, von = tag(ablauf), tag(seit)
    except ValueError as fehler:
        return "Ausnahme Zeile %d (%s): %s." % (nr, kennung, fehler)
    if von > heute:
        return "Ausnahme Zeile %d (%s): seit liegt in der Zukunft (%s, heute %s)." % (nr, kennung, seit, heute)
    if bis < von:
        return "Ausnahme Zeile %d (%s): Ablauf liegt vor seit (%s < %s)." % (nr, kennung, ablauf, seit)
    if (bis - von).days > HOECHSTFRIST_TAGE:
        return ("Ausnahme Zeile %d (%s): länger als %d Tage ab seit (%s bis %s). "
                "Eine unbefristete Ausnahme gibt es nicht." % (nr, kennung, HOECHSTFRIST_TAGE, seit, ablauf))
    if bis < heute:
        return ("Ausnahme abgelaufen (Zeile %d): %s, Issue %s, Ablauf %s, heute %s. "
                "Paket aktualisieren oder im Issue neu begruenden." % (nr, kennung, issue, ablauf, heute))
    return None


def ausnahmen(datei, heute_text):
    heute = tag(heute_text)
    fehler = 0
    for nr, zeile in enumerate(open(datei), 1):
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#"):
            continue
        felder = zeile.split()
        meldung = pruefe_ausnahme(nr, felder, heute)
        if meldung:
            print("FEHLER", meldung)
            fehler = 1
        else:
            print("ID", felder[0])
    return fehler


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
        elif sys.argv[1] == "ausnahmen":
            sys.exit(ausnahmen(sys.argv[2], sys.argv[3]))
        else:
            raise ValueError("unbekannter Modus " + sys.argv[1])
    except Exception as fehler:
        print("UNGEMESSEN Auswertung brach ab: %r" % (fehler,))
        sys.exit(2)
