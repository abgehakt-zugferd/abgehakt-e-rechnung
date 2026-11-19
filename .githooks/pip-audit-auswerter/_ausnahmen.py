"""Ausnahmen-Datei lesen und pruefen (privat, importiert von pip_audit_auswerten).

Format: `Kennung Issue Ablauf seit`, Kommentare mit #, leere Datei erlaubt.
Ablauf und seit muessen echte Kalendertage sein; Ablauf hoechstens
`hoechstfrist` Tage nach seit; abgelaufen ab dem Tag nach dem Ablauf.
"""
import datetime
import re

_KENNUNG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_ISSUE = re.compile(r"#?\d+")


def _tag(text):
    """Ein echter Kalendertag JJJJ-MM-TT, sonst ValueError."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        raise ValueError("Datum '%s' ist nicht JJJJ-MM-TT" % text)
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise ValueError("Datum %s ist kein Kalendertag" % text)


def lies_ausnahmen(pfad, heute_tag, hoechstfrist):
    """Liest die Ausnahmen-Datei. Gibt ({kennung: nr}, fehler_zeilen).

    Ein leerer Pfad (z. B. eine leere Shell-Variable) ist wie eine fehlende Datei:
    still abzuschalten wuerde eine Ausnahme verdecken.
    """
    if not pfad:
        return ({}, ["NICHT GEMESSEN Ausnahmen-Datei fehlt: (leerer Pfad)"])
    try:
        f = open(pfad, encoding="utf-8")
    except FileNotFoundError:
        return ({}, ["NICHT GEMESSEN Ausnahmen-Datei fehlt: %s" % pfad])
    ausnahmen = {}
    fehler = []
    with f:
        for nr, roh in enumerate(f, 1):
            zeile = roh.strip()
            if not zeile or zeile.startswith("#"):
                continue
            felder = zeile.split()
            meldung = _pruefe_ausnahme(nr, felder, heute_tag, hoechstfrist)
            if meldung:
                fehler.append("NICHT GEMESSEN " + meldung)
            else:
                ausnahmen[felder[0]] = nr
    return (ausnahmen, fehler)


def _pruefe_ausnahme(nr, felder, heute, hoechstfrist):
    if len(felder) != 4:
        return ("Ausnahme Zeile %d unvollstaendig: erwartet "
                "'Kennung Issue Ablauf seit', gefunden: %s" % (nr, " ".join(felder)))
    kennung, issue, ablauf, seit = felder
    if not _KENNUNG.fullmatch(kennung):
        return "Ausnahme Zeile %d: Kennung '%s' ist keine gueltige Kennung." % (nr, kennung)
    if not _ISSUE.fullmatch(issue):
        return "Ausnahme Zeile %d (%s): Issue '%s' ist keine Nummer." % (nr, kennung, issue)
    try:
        bis, von = _tag(ablauf), _tag(seit)
    except ValueError as e:
        return "Ausnahme Zeile %d (%s): %s." % (nr, kennung, e)
    if von > heute:
        return ("Ausnahme Zeile %d (%s): seit liegt in der Zukunft (%s, heute %s)."
                % (nr, kennung, seit, heute))
    if bis < von:
        return "Ausnahme Zeile %d (%s): Ablauf liegt vor seit (%s < %s)." % (nr, kennung, ablauf, seit)
    if (bis - von).days > hoechstfrist:
        return ("Ausnahme Zeile %d (%s): laenger als %d Tage ab seit (%s bis %s)."
                % (nr, kennung, hoechstfrist, seit, ablauf))
    if bis < heute:
        return ("Ausnahme abgelaufen (Zeile %d): %s, Ablauf %s, heute %s."
                % (nr, kennung, ablauf, heute))
    return None
