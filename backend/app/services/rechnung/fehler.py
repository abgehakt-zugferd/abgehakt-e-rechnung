"""Fachlicher Fehler der Rechnungsdienste.

Die Dienste kennen kein HTTP: Sie melden einen Fehler mit Statuscode und Text,
die Schicht darueber entscheidet, wie er beim Nutzer ankommt.
"""


class FinalisierungWarnung(Exception):
    """Mustang meldet beim Finalisieren Warnungen, die der Nutzer noch nicht bestätigt hat.

    Nichts ist finalisiert: Rollback ist erfolgt, die Rechnung bleibt Entwurf. `warnungen`
    sind Mustang-Befunde {regel, text, schwere}; `schluessel` nennt sie für die Bestätigung.
    """

    def __init__(self, warnungen: list[dict]):
        super().__init__("Mustang meldet Warnungen: " + ", ".join(warnungsschluessel(w) for w in warnungen))
        self.warnungen = warnungen

    @property
    def schluessel(self) -> list[str]:
        return sorted({warnungsschluessel(w) for w in self.warnungen})


def warnungsschluessel(befund: dict) -> str:
    """Wodurch eine Warnung bestätigt wird: ihre Regelkennung, sonst ihr Text."""
    return befund["regel"] or befund["text"]


class RechnungFehler(Exception):
    """Abgelehnte Rechnungsoperation mit Statuscode und Klartext-Meldung.

    `detail=None` entspricht einem HTTP-Abbruch ohne eigenen Text (nur Statuscode),
    wie frueher `HTTPException(404)`.
    """

    def __init__(self, status_code: int, detail: str | None = None):
        super().__init__(detail if detail is not None else "")
        self.status_code = status_code
        self.detail = detail
