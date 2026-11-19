#!/usr/bin/env python3
"""Gemeinsamer pip-audit-Auswerter fuer mehrere Python-Apps.

Eine App erzeugt ihre Anforderungen (uv export, pip-compile), laesst pip-audit
laufen und wertet Bericht und Exitcode hier aus. Wie die Pins entstehen und
wie pip-audit laeuft, bleibt Sache der App; dieser Auswerter prueft nur das
Ergebnis.

Subkommandos: vorbereiten, auswerten, locks. Siehe README.md.
"""
import argparse
import datetime
import json
import re
import sys

# Private Module erst hier laden: scheitert der Import (fehlende Datei,
# Syntaxfehler, jede andere Ausnahme), darf der CLI-Exit nicht 1 (LUECKE)
# sein — das waere eine Vertragsluecke. Der Fehler wird gemerkt und im
# __main__-Zweig als Exit 2 mit ERGEBNIS ausgegeben.
_IMPORT_FEHLER = None
try:
    from _ausnahmen import lies_ausnahmen, _tag
    from _bericht import (
        _norm,
        _pakete_sammeln,
        _pin_abgleich,
        _luecken_ausgabe,
        _ungenutzte_hinweise,
    )
except Exception as _fehler:  # noqa: BLE001 — Laden ist Messausfall, nicht Luecke
    _IMPORT_FEHLER = _fehler


# Hoechstfrist einer Ausnahme in Tagen, gerechnet ab `seit` (nicht ab heute:
# sonst wanderte die Frist mit jedem Lauf mit und alterte nie).
HOECHSTFRIST_TAGE = 30


# ── vorbereiten ────────────────────────────────────────────────────────────

_PIN_ANFANG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*==")
# Entfernt `; marker` aus einer Pin-Zeile (mit oder ohne Leerzeichen vor dem
# `;`), laesst ein trailing ` \` bzw. den Zeilenumbruch stehen und wirkt auch
# in einer letzten Zeile ohne Zeilenumbruch am Dateiende ($).
_MARKER = re.compile(r" *; .*?(?= \\|\n|$)")


def vorbereiten(pfad):
    """Entfernt Umgebungsmarker aus Pin-Zeilen; gibt den Text zurueck.

    Nur Zeilen, die mit einem Pin beginnen, werden beruehrt; Kommentare,
    Leerzeilen und eingerueckte --hash-/#-Folgezeilen bleiben unveraendert.
    """
    with open(pfad, encoding="utf-8") as f:
        zeilen = f.readlines()
    out = []
    for zeile in zeilen:
        if _PIN_ANFANG.match(zeile):
            zeile = _MARKER.sub("", zeile, count=1)
        out.append(zeile)
    return "".join(out)


# ── auswerten ──────────────────────────────────────────────────────────────

def auswerten(pins_pfad, bericht_pfad, rc, ausnahmen_pfad, heute=None):
    """Wertet Bericht und Exitcode aus. Gibt (exit_code, zeilen) zurueck.

    Exit 0 sauber, 1 Luecke, 2 nicht gemessen. Jede Abweichung oder jeder
    Abbruch ergibt 2 mit einer NICHT GEMESSEN-Zeile als Grund.
    """
    try:
        return _auswerten(pins_pfad, bericht_pfad, rc, ausnahmen_pfad, heute)
    except Exception as fehler:  # noqa: BLE001 — Regel 5: Abbruch ist Messausfall
        return (2, ["NICHT GEMESSEN Auswertung brach ab: %r" % (fehler,),
                    "ERGEBNIS NICHT GEMESSEN (Auswertung brach ab)"])


def _auswerten(pins_pfad, bericht_pfad, rc, ausnahmen_pfad, heute):
    if heute is None:
        heute = datetime.date.today().isoformat()
    heute_tag = _tag(heute)
    if rc not in (0, 1):
        return (2, ["NICHT GEMESSEN pip-audit endete mit rc=%d (nur 0/1 zulaessig)" % rc,
                    "ERGEBNIS NICHT GEMESSEN (0 Pakete)"])
    pins, _pin_zeilen, unbekannt = _lies_pins(pins_pfad)
    zeilen = []
    for z in unbekannt:
        zeilen.append("NICHT GEMESSEN unbekannte Pin-Zeile: %s" % z)
    if unbekannt:
        return (2, zeilen + ["ERGEBNIS NICHT GEMESSEN (0 Pakete)"])
    if not pins:
        zeilen.append("NICHT GEMESSEN Pin-Datei enthaelt kein einziges gepinntes Paket")
        return (2, zeilen + ["ERGEBNIS NICHT GEMESSEN (0 Pakete)"])
    ausnahmen, ausnahme_fehler = lies_ausnahmen(ausnahmen_pfad, heute_tag, HOECHSTFRIST_TAGE)
    zeilen += ausnahme_fehler
    if ausnahme_fehler:
        return (2, zeilen + ["ERGEBNIS NICHT GEMESSEN (0 Pakete)"])
    bericht = json.load(open(bericht_pfad, encoding="utf-8"))
    pakete = bericht["dependencies"]
    if not isinstance(pakete, list):
        return (2, ["NICHT GEMESSEN Bericht ohne dependencies-Liste",
                    "ERGEBNIS NICHT GEMESSEN (0 Pakete)"])
    if not pakete:
        zeilen.append("NICHT GEMESSEN Bericht nennt kein einziges Paket")
        return (2, zeilen + ["ERGEBNIS NICHT GEMESSEN (0 Pakete)"])
    return _bewerte(pins, pakete, rc, ausnahmen, zeilen)


def _lies_pins(pfad):
    """Liest die Pin-Datei. Gibt (Pins, Original-Zeilen, unbekannt).

    Pins ist ein Dict {(normierter Name, Version): Originalname} — ein
    Plattform-Split (`x==0.9 ; win32`, `x==1.0 ; linux`) ergibt zwei Paare,
    ein exakt doppelter Eintrag zaehlt einmal.
    """
    pins = {}
    zeilen = []
    unbekannt = []
    folge = re.compile(r"^    (--hash=|#)")
    pin_re = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^ ;\\]+)")
    with open(pfad, encoding="utf-8") as f:
        for roh in f:
            zeile = roh.rstrip("\n")
            zeilen.append(zeile)
            if not zeile.strip() or zeile.startswith("#") or folge.match(zeile):
                continue
            treffer = pin_re.match(zeile)
            if treffer:
                schluessel = (_norm(treffer.group(1)), treffer.group(2))
                pins.setdefault(schluessel, treffer.group(1))
            else:
                unbekannt.append(zeile)
    return pins, zeilen, unbekannt


def _bewerte(pins, pakete, rc, ausnahmen, zeilen):
    """Sammelt Pakete/Luecken, gleicht Pins ab, gibt Luecken aus und wichtet."""
    gesehen, luecken, nicht_gemessen = _pakete_sammeln(pakete, zeilen)
    nicht_gemessen |= _pin_abgleich(pins, gesehen, zeilen)
    if rc == 1 and not luecken:
        zeilen.append("NICHT GEMESSEN pip-audit rc=1 ohne eine Luecke im Bericht")
        nicht_gemessen = True
    fund_zeilen = _luecken_ausgabe(luecken, ausnahmen, zeilen)
    zeilen += fund_zeilen
    _ungenutzte_hinweise(ausnahmen, luecken, zeilen)
    if nicht_gemessen:
        zeilen.append("ERGEBNIS NICHT GEMESSEN (%d Pakete)" % len(pakete))
        return (2, zeilen)
    if fund_zeilen:
        zeilen.append("ERGEBNIS LUECKE (%d Pakete)" % len(pakete))
        return (1, zeilen)
    zeilen.append("ERGEBNIS SAUBER (%d Pakete)" % len(pakete))
    return (0, zeilen)


# ── locks ──────────────────────────────────────────────────────────────────

def locks(versioniert_pfad, eingetragen_pfad):
    """Exit 2, wenn ein versioniertes Lock nicht eingetragen ist; sonst 0."""
    versioniert = _lies_pfad_liste(versioniert_pfad)
    eingetragen = set(_lies_pfad_liste(eingetragen_pfad))
    fehlt = [p for p in versioniert if p not in eingetragen]
    if not fehlt:
        return (0, [])
    return (2, ["NICHT GEMESSEN versioniert, aber nicht eingetragen: %s" % p for p in fehlt])


def _lies_pfad_liste(pfad):
    with open(pfad, encoding="utf-8") as f:
        return [zeile.strip() for zeile in f if zeile.strip()]


# ── CLI ────────────────────────────────────────────────────────────────────

def main(argv=None):
    teile = argparse.ArgumentParser(prog="pip_audit_auswerten.py")
    sub = teile.add_subparsers(dest="modus", required=True)
    p_v = sub.add_parser("vorbereiten")
    p_v.add_argument("datei")
    p_a = sub.add_parser("auswerten")
    p_a.add_argument("--pins", required=True)
    p_a.add_argument("--bericht", required=True)
    p_a.add_argument("--rc", type=int, required=True)
    p_a.add_argument("--ausnahmen", required=True)
    p_a.add_argument("--heute")
    p_l = sub.add_parser("locks")
    p_l.add_argument("--versioniert", required=True)
    p_l.add_argument("--eingetragen", required=True)
    args = teile.parse_args(argv)
    if args.modus == "vorbereiten":
        sys.stdout.write(vorbereiten(args.datei))
        return 0
    if args.modus == "auswerten":
        rc, zeilen = auswerten(args.pins, args.bericht, args.rc, args.ausnahmen, args.heute)
        for z in zeilen:
            print(z)
        return rc
    if args.modus == "locks":
        rc, zeilen = locks(args.versioniert, args.eingetragen)
        for z in zeilen:
            print(z)
        return rc
    return 2


def _abbruch_strom(argv):
    """stderr bei vorbereiten/locks (stdout = Pin-/Listenkanal), sonst stdout."""
    if argv and argv[0] in ("vorbereiten", "locks"):
        return sys.stderr
    return sys.stdout


if __name__ == "__main__":
    try:
        if _IMPORT_FEHLER is not None:
            raise _IMPORT_FEHLER
        sys.exit(main())
    except Exception as fehler:  # noqa: BLE001 — Regel 5: Abbruch ist Messausfall
        strom = _abbruch_strom(sys.argv[1:])
        print("NICHT GEMESSEN Auswertung brach ab: %r" % (fehler,), file=strom)
        print("ERGEBNIS NICHT GEMESSEN (Auswertung brach ab)", file=strom)
        sys.exit(2)
