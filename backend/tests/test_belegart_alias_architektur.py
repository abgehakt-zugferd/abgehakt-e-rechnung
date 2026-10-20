"""Architekturregel #172: kein Rohzugriff auf invoice_type fuer Belegart-Filter.

Ausserhalb von services/belegart.py:
- kein Vergleich mit Belegart-Literal (==, !=, in)
- kein invoice_type.is_(...) und kein invoice_type.in_(...)
  (nur belegart_filter / belegart(...).intern / ist_storno)

Kommentarzeilen zaehlen nicht; jede Fundstelle wird einzeln gemeldet.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.services import belegart as belegart_modul

APP = Path(__file__).resolve().parents[1] / "app"
ERLAUBT = {APP / "services" / "belegart.py"}

# Interne Formen und Aliase aus der einzigen Quelle — der Waechter driftet nicht.
_BELEGART_LITERALE = frozenset(
    str(k) for k in belegart_modul._ALIASES if k is not None
) | frozenset(
    art.intern for art in belegart_modul._ALIASES.values() if art.intern is not None
)


def _ist_invoice_type_zugriff(knoten: ast.AST) -> bool:
    if isinstance(knoten, ast.Name) and knoten.id == "invoice_type":
        return True
    if isinstance(knoten, ast.Attribute) and knoten.attr == "invoice_type":
        return True
    return False


def _konstante_literale(knoten: ast.AST) -> set[str]:
    """String-Literale in Konstanten, Mengen, Listen, Tupeln."""
    gefundene: set[str] = set()
    if isinstance(knoten, ast.Constant) and isinstance(knoten.value, str):
        gefundene.add(knoten.value)
        return gefundene
    if isinstance(knoten, (ast.Set, ast.List, ast.Tuple)):
        for elt in knoten.elts:
            gefundene |= _konstante_literale(elt)
    return gefundene


def _vergleicht_mit_belegart(knoten: ast.Compare) -> bool:
    seiten = [knoten.left, *knoten.comparators]
    hat_invoice_type = any(_ist_invoice_type_zugriff(s) for s in seiten)
    if not hat_invoice_type:
        return False
    literale: set[str] = set()
    for seite in seiten:
        literale |= _konstante_literale(seite)
    return bool(literale & _BELEGART_LITERALE)


def _invoice_type_spaltenaufruf(knoten: ast.Call, methoden: frozenset[str]) -> bool:
    """True bei invoice_type.is_(...) oder invoice_type.in_(...), egal welches Argument."""
    func = knoten.func
    if not isinstance(func, ast.Attribute) or func.attr not in methoden:
        return False
    return _ist_invoice_type_zugriff(func.value)


def funde_in_quelle(quelle: str, rel: str = "probe.py") -> list[str]:
    """Verbotene Stellen; Kommentarzeilen uebersprungen. Treffer: rel:zeile: ausschnitt."""
    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return []

    zeilen = quelle.splitlines()
    funde: list[str] = []
    gesehen: set[int] = set()

    for knoten in ast.walk(baum):
        zeile = getattr(knoten, "lineno", None)
        if zeile is None or zeile in gesehen:
            continue
        if 1 <= zeile <= len(zeilen) and zeilen[zeile - 1].lstrip().startswith("#"):
            continue
        verboten = False
        if isinstance(knoten, ast.Compare):
            verboten = _vergleicht_mit_belegart(knoten)
        elif isinstance(knoten, ast.Call):
            verboten = _invoice_type_spaltenaufruf(knoten, frozenset({"in_", "is_"}))
        if not verboten:
            continue
        gesehen.add(zeile)
        ausschnitt = zeilen[zeile - 1].strip() if 1 <= zeile <= len(zeilen) else ""
        funde.append(f"{rel}:{zeile}: {ausschnitt}")
    return funde


def _treffer_in(pfad: Path) -> list[str]:
    quelle = pfad.read_text(encoding="utf-8")
    rel = str(pfad.relative_to(APP.parent))
    return funde_in_quelle(quelle, rel=rel)


def test_kein_rohvergleich_von_invoice_type_ausserhalb_belegart():
    dateien = sorted(p for p in APP.rglob("*.py") if p not in ERLAUBT)
    assert dateien, "kein Suchraum unter app/: der Waechter prueft nichts"

    treffer = [t for p in dateien for t in _treffer_in(p)]
    assert not treffer, (
        "Rohzugriff auf invoice_type (Literalvergleich oder .is_/.in_) "
        "(nur services/belegart.py darf die Rohformen kennen):\n"
        + "\n".join(treffer)
    )


@pytest.mark.parametrize(
    "quelle",
    [
        'if invoice.invoice_type == "credit_note":\n    pass\n',
        'if invoice.invoice_type != "self_billing":\n    pass\n',
        'if invoice.invoice_type in {"credit_note", "self_billing_storno"}:\n    pass\n',
        'if "credit_note" == invoice.invoice_type:\n    pass\n',
        'q.filter(Invoice.invoice_type.in_(["credit_note", "storno"]))\n',
        'q.filter(Invoice.invoice_type.in_(("credit",)))\n',
        'q.filter(Invoice.invoice_type.in_(rohwerte("credit_note")))\n',
        'q.filter(Invoice.invoice_type.is_(None))\n',
        'q.filter(Invoice.invoice_type.in_(STORNO_BELEGARTEN))\n',
        'if invoice_type == "prepayment":\n    pass\n',
        'if obj.invoice_type in {"storno"}:\n    pass\n',
    ],
)
def test_architektur_erkennt_rohvergleiche(quelle):
    funde = funde_in_quelle(quelle)
    assert funde, f"Rohzugriff nicht erkannt:\n{quelle}"


@pytest.mark.parametrize(
    "quelle",
    [
        '# invoice.invoice_type == "credit_note"\n',
        '# Invoice.invoice_type.is_(None)\n',
        'hinweis = "invoice_type == credit_note"\n',
        'if belegart(invoice.invoice_type).intern == "credit_note":\n    pass\n',
        'if belegart(invoice.invoice_type).intern in {"credit_note"}:\n    pass\n',
        'q.filter(belegart_filter(Invoice.invoice_type, "credit_note"))\n',
        'q.filter(belegart_filter(Invoice.invoice_type, None, "prepayment"))\n',
        'Invoice(invoice_type="credit_note")\n',
        'invoice.invoice_type = "credit_note"\n',
        'if status == "issued":\n    pass\n',
    ],
)
def test_architektur_laesst_aufgeloeste_und_kommentare_durch(quelle):
    funde = funde_in_quelle(quelle)
    assert not funde, f"Falscher Alarm:\n{quelle}\n{funde}"


def test_architektur_meldet_jede_fundstelle_einzeln():
    quelle = (
        'if a.invoice_type == "credit_note":\n'
        '    pass\n'
        'if b.invoice_type == "storno":\n'
        '    pass\n'
    )
    funde = funde_in_quelle(quelle, rel="zwei.py")
    assert len(funde) == 2, funde
    assert funde[0].startswith("zwei.py:1:")
    assert funde[1].startswith("zwei.py:3:")


def test_architektur_mutation_neue_rohvergleichszeile_wird_rot():
    """Nachbar und Mutation (L30): eingefuegte Literalzeile muss auffallen."""
    opfer = APP / "services" / "storno_wirkung.py"
    original = opfer.read_text(encoding="utf-8")
    assert 'invoice_type == "credit_note"' not in original
    nachbar = funde_in_quelle(original, rel="storno_wirkung.py")
    assert not nachbar, f"Nachbar schon rot: {nachbar}"

    mutiert = original + '\n_PROBE = Invoice.invoice_type == "credit_note"\n'
    funde = funde_in_quelle(mutiert, rel="storno_wirkung.py")
    assert funde, "Mutation ohne Treffer — Waechter greift die neue Zeile nicht"
    assert any("credit_note" in f for f in funde)
    assert opfer.read_text(encoding="utf-8") == original


def test_architektur_mutation_neue_is_none_zeile_wird_rot():
    """is_(None) auf invoice_type ausserhalb belegart.py muss auffallen."""
    opfer = APP / "services" / "dashboard_kennzahlen.py"
    original = opfer.read_text(encoding="utf-8")
    nachbar = funde_in_quelle(original, rel="dashboard_kennzahlen.py")
    assert not nachbar, f"Nachbar schon rot: {nachbar}"

    mutiert = original + "\n_PROBE = Invoice.invoice_type.is_(None)\n"
    funde = funde_in_quelle(mutiert, rel="dashboard_kennzahlen.py")
    assert funde, "Mutation is_(None) ohne Treffer"
    assert any("is_(None)" in f for f in funde)
    assert opfer.read_text(encoding="utf-8") == original
