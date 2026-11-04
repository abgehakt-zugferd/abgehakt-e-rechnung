"""Der eine Durchlass, durch den bezahlt_am nach dem Setzen noch geaendert wird (#278).

bezahlt_am ist nach dem Setzen unveraenderlich (invoice_guard, Entscheidung
2026-09-30). Eine Korrektur ist nur auf einem Weg erlaubt: Der Korrekturdienst
(`zahlungsdatum_korrektur.korrigieren`) oeffnet den Durchlass fuer GENAU diesen
Beleg und schliesst ihn nach dem Flush wieder. Der Durchlass traegt den Grund;
der Audit-Listener schreibt ihn in dieselbe Zeile des Aenderungsprotokolls, in
derselben Transaktion wie die Aenderung selbst. Ohne Grund gibt es keinen
Durchlass, und ohne Durchlass keinen Protokolleintrag mit Grund.

Dieses Modul importiert nichts aus der Anwendung: Guard und Audit lesen es,
beide muessen es ohne Kreis laden koennen.
"""
from contextlib import contextmanager

_KEY = "_zahlungsdatum_korrektur"

# Schluessel im Protokolleintrag (audit_log.new_values), unter dem der Grund steht.
GRUND_FELD = "bezahlt_am_grund"


def grund_fuer(session, invoice_id) -> str | None:
    """Grund der laufenden Korrektur dieses Belegs, sonst None (Durchlass zu)."""
    grund = session.info.get(_KEY, {}).get(invoice_id)
    return grund if grund and grund.strip() else None


@contextmanager
def durchlass(session, invoice_id, grund: str):
    """Oeffnet den Durchlass fuer einen Beleg, solange der Block laeuft."""
    offen = session.info.setdefault(_KEY, {})
    offen[invoice_id] = grund
    try:
        yield
    finally:
        offen.pop(invoice_id, None)
