"""
Sicherer Temp-Datei-Umgang überall dort, wo der Router Temp-Dateien erzeugt.
Bug-Historie: `tempfile.mktemp()` ist deprecated und hat eine TOCTOU-Race-Condition
(ein Angreifer kann zwischen Namensvergabe und Öffnen die Datei unterschieben).
Fix: `tempfile.mkstemp()` (atomar).

#98 P1: früher ein MagicMock-Call-Spy (Validator + Mustang komplett weggepatcht) —
der prüfte nur „mktemp nicht aufgerufen" und war Rauschen neben den echten
`pruefen`-Integrationstests. Ein *funktionaler* Test kann diese Regression nicht
fangen (auch `mktemp` „funktioniert" ja), darum hier ein Quell-Regression-Guard
direkt auf dem echten Source: die unsichere API darf nicht zurückkehren.

#141/#142: der Temp-Datei-Umgang ist aus `validate_invoice_route` nach
`_run_validation` gewandert (geteilt von `POST /pruefen` und dem Entwurfs-Edit), und
mit der Entwurfs-Vorschau kam eine zweite Stelle dazu. Der Guard ist deshalb über
alle erzeugenden Funktionen parametrisiert statt an eine gebunden — die Aussage
(„`mktemp` darf nicht zurückkehren, `mkstemp` muss da sein") bleibt wörtlich und
deckt jetzt mehr Stellen ab als vorher. Wandert der Code erneut, zeigt der Guard auf
die Funktion, die den Aufruf tatsächlich enthält.
"""
import inspect

import pytest

from app.routers.invoices import _run_validation, preview_pdf

ERZEUGT_TEMPDATEIEN = [
    pytest.param(_run_validation, id="_run_validation"),
    pytest.param(preview_pdf, id="preview_pdf"),
]


@pytest.mark.parametrize("func", ERZEUGT_TEMPDATEIEN)
def test_uses_atomic_mkstemp_not_deprecated_mktemp(func):
    src = inspect.getsource(func)
    # "mkstemp" enthält "mktemp" NICHT als Teilstring (mk-s-temp vs. mk-temp),
    # daher fängt dieser Check gezielt nur die unsichere Variante.
    assert "tempfile.mktemp(" not in src, (
        f"tempfile.mktemp() (TOCTOU) in {func.__name__} — durch tempfile.mkstemp() "
        "oder NamedTemporaryFile(delete=False) ersetzen."
    )
    assert "tempfile.mkstemp(" in src, (
        f"Erwartete atomare tempfile.mkstemp()-Nutzung in {func.__name__} nicht "
        "gefunden — wurde der Temp-Datei-Umgang umgebaut?"
    )
