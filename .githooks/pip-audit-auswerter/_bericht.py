"""Bericht- und Luecken-Auswertung (privat, importiert von pip_audit_auswerten).

Ausgelagert aus pip_audit_auswerten.py, damit jede Moduldatei unter 300 Zeilen
bleibt. _norm lebt hier (und wird zurueckimportiert), damit _bericht.py nichts
aus pip_audit_auswerten importiert — sonst gaebe es einen Zirkelimport, weil
pip_audit_auswerten die Funktionen hierher importiert.
"""
import re


def _norm(name):
    """PEP 503: PyYAML/pyyaml, Typing_Extensions/typing-extensions."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _pakete_sammeln(pakete, zeilen):
    """Prueft Form je Paket, sammelt gesehen (norm -> Liste) und Luecken."""
    gesehen = {}
    luecken = []
    nicht_gemessen = False
    for p in pakete:
        if not isinstance(p, dict):
            zeilen.append("NICHT GEMESSEN Eintrag ist kein Paket-Objekt: %r" % (p,))
            nicht_gemessen = True
            continue
        name = p.get("name")
        version = p.get("version")
        if not (isinstance(name, str) and isinstance(version, str)):
            zeilen.append("NICHT GEMESSEN Paket ohne Name oder Version: %r" % (p,))
            nicht_gemessen = True
            continue
        gesehen.setdefault(_norm(name), [])
        eintrag = (name, version)
        if eintrag not in gesehen[_norm(name)]:
            gesehen[_norm(name)].append(eintrag)
        if p.get("skip_reason"):
            zeilen.append("NICHT GEMESSEN %s uebersprungen: %s" % (name, p["skip_reason"]))
            nicht_gemessen = True
            continue
        vulns = p.get("vulns")
        if not isinstance(vulns, list):
            zeilen.append("NICHT GEMESSEN %s ohne vulns-Liste im Bericht" % name)
            nicht_gemessen = True
            continue
        for v in vulns:
            if not isinstance(v, dict) or not v.get("id"):
                zeilen.append("NICHT GEMESSEN %s: Luecke ohne Kennung" % name)
                nicht_gemessen = True
                continue
            luecken.append((name, version, v))
    return gesehen, luecken, nicht_gemessen


def _pin_abgleich(pins, gesehen, zeilen):
    """Regel 1: Mengenabgleich der Paare (normierter Name, Version) in beide
    Richtungen. Jedes gepinnte Paar muss im Bericht stehen, jedes Berichtspaar
    muss gepinnt sein — sonst ungeprueft. Zwei Versionen eines Namens sind
    zulaessig, wenn beide gepinnt sind (Plattform-Split); eine ungepinnte
    zweite Version faellt als Berichtspaar ohne Pin heraus. Gibt
    nicht_gemessen."""
    bericht = {}
    versionen = {}
    for n, eintraege in gesehen.items():
        for orig, ver in eintraege:
            bericht.setdefault((n, ver), orig)
            if ver not in versionen.setdefault(n, []):
                versionen[n].append(ver)
    fehlt = sorted(set(pins) - set(bericht))
    fremd = sorted(set(bericht) - set(pins))
    for n, ver in fehlt:
        if n in versionen:
            zeilen.append("NICHT GEMESSEN %s gepinnt %s, im Bericht %s"
                          % (pins[(n, ver)], ver, ", ".join(sorted(versionen[n]))))
        else:
            zeilen.append("NICHT GEMESSEN %s %s gepinnt, aber nicht im Bericht"
                          % (pins[(n, ver)], ver))
    for n, ver in fremd:
        zeilen.append("NICHT GEMESSEN %s %s im Bericht, aber nicht gepinnt"
                      % (bericht[(n, ver)], ver))
    return bool(fehlt or fremd)


def _luecken_ausgabe(luecken, ausnahmen, zeilen):
    """Gibt Luecken aus. Je Paket+Version zaehlt eine Luecke einmal, wenn ihre
    Kennungsmenge ({id} ∪ aliases) eine andere ueberlappt (Regel 6). Eine
    Ausnahme gilt je Advisory (eigene Kennungsmenge), nicht je Komponente."""
    # Zunaechst identische (name, version, id)-Eintraege dedup (Regel 6).
    dedup = []
    gesehen = set()
    for name, version, v in luecken:
        if (name, version, v["id"]) in gesehen:
            continue
        gesehen.add((name, version, v["id"]))
        dedup.append((name, version, v))
    # Je (name, version): connected components ueberlappender Kennungsmengen.
    nach_name = {}
    for name, version, v in dedup:
        nach_name.setdefault((name, version), []).append(v)
    fund_zeilen = []
    for (name, version), vs in nach_name.items():
        for komponente in _kennung_komponenten(vs):
            _komponente_ausgeben(komponente, name, version, ausnahmen, zeilen, fund_zeilen)
    return fund_zeilen


def _kennung_komponenten(vulns):
    """Gruppiert vulns nach ueberlappenden Kennungsmengen ({id} ∪ aliases)."""
    mengen = [{v["id"], *v.get("aliases", [])} for v in vulns]
    gesehen = [False] * len(vulns)
    komponenten = []
    for i in range(len(vulns)):
        if gesehen[i]:
            continue
        comp = []
        stack = [i]
        gesehen[i] = True
        while stack:
            j = stack.pop()
            comp.append(vulns[j])
            for k in range(len(vulns)):
                if not gesehen[k] and mengen[j] & mengen[k]:
                    gesehen[k] = True
                    stack.append(k)
        komponenten.append(comp)
    return komponenten


def _komponente_ausgeben(komponente, name, version, ausnahmen, zeilen, fund_zeilen):
    """Eine Ausnahme gilt je Advisory: ein Eintrag ist nur ausgenommen, wenn
    seine eigene Menge ({id} ∪ aliases) die Ausnahme trifft — nicht transitiv
    ueber die Komponente. Die Komponente dient nur der Anzeige: mindestens
    ein nicht ausgenommener Eintrag ergibt genau eine LUECKE-Zeile; sind alle
    ausgenommen, ergibt sie je Eintrag AUSGENOMMEN."""
    frei = []
    for v in komponente:
        treffer = {v["id"], *v.get("aliases", [])} & set(ausnahmen)
        if treffer:
            for kennung in sorted(treffer):
                zeilen.append("AUSGENOMMEN %s %s %s %s" % (kennung, name, version, v["id"]))
        else:
            frei.append(v)
    if not frei:
        return
    erster = frei[0]
    aliase = ", ".join(erster.get("aliases") or [])
    fix = ", ".join(erster.get("fix_versions") or []) or "keiner Fassung"
    fund_zeilen.append("LUECKE %s %s %s (%s) behoben in %s"
                       % (name, version, erster["id"], aliase, fix))


def _ungenutzte_hinweise(ausnahmen, luecken, zeilen):
    """Regel 9: eine Ausnahme, die zu keiner Luecke passt, ist ein HINWEIS."""
    benutzt = set()
    for _n, _v, v in luecken:
        for k in {v["id"], *v.get("aliases", [])}:
            if k in ausnahmen:
                benutzt.add(k)
    for kennung in sorted(set(ausnahmen) - benutzt):
        zeilen.append("HINWEIS Ausnahme %s passt zu keiner Luecke" % kennung)
