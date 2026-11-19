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


def ist_verbindungsfehler(fehler: Exception) -> bool:
    """Nur „Server nicht erreichbar“ rechtfertigt einen Skip, nicht jeder OperationalError.

    Hat die Ausnahme einen SQLSTATE, entscheidet die Klasse: 08 = Verbindungsfehler,
    jede andere Klasse = keiner (auch wenn der Text passt). Ohne SQLSTATE bleibt der
    Meldungstext maßgeblich (Verbindung kam nie zustande).
    """
    code = _sqlstate(fehler)
    if code is not None:
        return code.startswith("08")
    text_ = str(fehler).lower()
    return any(m in text_ for m in (
        "could not connect", "connection refused", "could not translate host",
        "name or service not known", "timeout expired"))
