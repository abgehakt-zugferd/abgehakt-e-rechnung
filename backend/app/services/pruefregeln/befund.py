"""Der einheitliche Befund der Rechnungspruefung.

Issue bleibt unter app.services.validator importierbar (steuerstatus.py und
ersatzrechnung.py holen ihn dort innerhalb ihrer Funktionen); dieses Modul
ist die eine Quelle.
"""
from dataclasses import dataclass


@dataclass
class Issue:
    code: str
    severity: str  # error | warning | info
    message: str
    field: str | None = None
