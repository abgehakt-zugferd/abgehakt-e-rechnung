"""Enger Skip-Grund: nur „Server nicht erreichbar“, nicht jeder OperationalError."""


def ist_verbindungsfehler(fehler: Exception) -> bool:
    """Nur „Server nicht erreichbar“ rechtfertigt einen Skip, nicht jeder OperationalError."""
    text_ = str(fehler).lower()
    return any(m in text_ for m in (
        "could not connect", "connection refused", "could not translate host",
        "name or service not known", "timeout expired"))
