"""Fachlicher Fehler der Rechnungsdienste.

Die Dienste kennen kein HTTP: Sie melden einen Fehler mit Statuscode und Text,
die Schicht darueber entscheidet, wie er beim Nutzer ankommt.
"""


class RechnungFehler(Exception):
    """Abgelehnte Rechnungsoperation mit Statuscode und Klartext-Meldung.

    `detail=None` entspricht einem HTTP-Abbruch ohne eigenen Text (nur Statuscode),
    wie frueher `HTTPException(404)`.
    """

    def __init__(self, status_code: int, detail: str | None = None):
        super().__init__(detail if detail is not None else "")
        self.status_code = status_code
        self.detail = detail
