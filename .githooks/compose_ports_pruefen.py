#!/usr/bin/env python3
"""Positivliste fuer veroeffentlichte Ports in der JSON-Normalform von `compose config`.

Aufruf: compose_ports_pruefen.py <json-datei> <bezeichnung>

Rot ist: jede Port-Angabe, deren host_ip nicht 127.0.0.1 ist (auch fehlendes host_ip,
auch eine Angabe ohne published, denn sie veroeffentlicht einen zufaelligen Host-Port
an allen Schnittstellen), und `network_mode: host`. Compose hat die Kurz- und Langform,
Anfuehrungszeichen und Variablen schon aufgeloest; hier wird nur die Normalform gelesen.
Exit 0 = gruen, 1 = Fund, 2 = nicht gemessen (JSON nicht lesbar oder ohne Dienste).
"""
import json
import sys

LOOPBACK = "127.0.0.1"


def funde(config: dict) -> list[str]:
    treffer = []
    for name, dienst in sorted((config.get("services") or {}).items()):
        if dienst.get("network_mode") == "host":
            treffer.append(f"Dienst {name}: network_mode: host")
        for port in dienst.get("ports") or []:
            if port.get("host_ip") != LOOPBACK:
                treffer.append(f"Dienst {name}: host_ip={port.get('host_ip')!r} "
                               f"published={port.get('published')!r} target={port.get('target')!r}")
    return treffer


def main(argv: list[str]) -> int:
    try:
        with open(argv[1], encoding="utf-8") as datei:
            config = json.load(datei)
    except (OSError, ValueError, IndexError) as fehler:
        print(f"netz: NICHT GEMESSEN - JSON nicht lesbar: {fehler}", file=sys.stderr)
        return 2
    dienste = config.get("services") if isinstance(config, dict) else None
    if (not isinstance(dienste, dict) or not dienste):
        # Ohne Dienste ist nichts gemessen; "keine Funde" waere dann eine leere Menge.
        print("netz: NICHT GEMESSEN - die Normalform enthaelt keine Dienste (services fehlt, "
              "ist leer oder kein Objekt)", file=sys.stderr)
        return 2
    treffer = funde(config)
    for zeile in treffer:
        print(f"  {argv[2]}: {zeile}")
    return 1 if treffer else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
