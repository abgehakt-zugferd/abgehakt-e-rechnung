"""Enger Skip-Grund: nur „Server nicht erreichbar“, nicht jeder OperationalError."""


def _sqlstate(fehler: Exception) -> str | None:
    """psycopg: SQLSTATE an fehler.orig.pgcode bzw. .sqlstate; fehlt beides → None."""
    orig = getattr(fehler, "orig", None)
    if orig is None:
        return None
    for attr in ("pgcode", "sqlstate"):
        wert = getattr(orig, attr, None)
        if isinstance(wert, str) and len(wert) >= 2:
            return wert
    return None


# Positivliste: echte Erreichbarkeits-/Verbindungsabbrüche (nicht 08P01, 08007).
_VERBINDUNGS_SQLSTATES = frozenset({"08000", "08001", "08003", "08004", "08006"})


def ist_verbindungsfehler(fehler: Exception) -> bool:
    """Nur „Server nicht erreichbar“ rechtfertigt einen Skip, nicht jeder OperationalError.

    Hat die Ausnahme einen SQLSTATE, entscheidet die Positivliste 08000/08001/08003/
    08004/08006: nur diese sind Verbindungsfehler. Jede andere SQLSTATE (auch 08P01
    protocol_violation und 08007 transaction_resolution_unknown) ist keiner, auch
    wenn der Text passt. Ohne SQLSTATE bleibt der Meldungstext maßgeblich
    (Verbindung kam nie zustande).
    """
    code = _sqlstate(fehler)
    if code is not None:
        return code in _VERBINDUNGS_SQLSTATES
    text_ = str(fehler).lower()
    return any(m in text_ for m in (
        "could not connect", "connection refused", "could not translate host",
        "name or service not known", "timeout expired"))
