"""
Herkunftsprüfung: fremde Webseiten dürfen nicht in das Archiv schreiben.

Die Anwendung hat bewusst keine Anmeldung — wer die Oberfläche erreicht, darf
alles (siehe SECURITY.md). Daraus folgt aber nicht, dass jede beliebige Seite im
Browser mitschreiben darf: Ein Formular auf einer fremden Seite darf ohne
CORS-Vorabfrage an `http://localhost:3000` senden. Die Antwort kann die fremde
Seite nicht lesen (Same-Origin-Policy), aber der Schreibvorgang findet statt —
und Schreibvorgänge sind hier endgültig. Eine so angelegte und finalisierte
Rechnung ist nach GoBD nicht mehr löschbar, nur stornierbar, und ihre Nummer ist
vergeben.

**Warum `Origin` und kein Token.** Ein CSRF-Token braucht einen Ort, an dem es
zwischen zwei Anfragen liegt — also eine Sitzung und ein Cookie. Beides hat die
Anwendung nicht, und beides einzuführen, um ein Feld in jedes der Formulare zu
tragen, wäre für ein Werkzeug ohne Anmeldung unverhältnismäßig. Browser senden
`Origin` bei jedem POST, auch bei einem Formular-POST von einer fremden Seite.
Genau der Fall, um den es geht, trägt den Kopf also immer bei sich.

**Warum eine fehlende Angabe erlaubt bleibt.** `curl`, Skripte und die Testsuite
senden keinen `Origin`. Sie zu sperren brächte keinen Schutz: ein Browser lässt
den Kopf bei einer fremden Anfrage nicht weg, ein Angreifer kann ihn also nicht
unterdrücken. Wer ohne Browser zugreift, sitzt schon am Rechner — dort ist
ohnehin alles erlaubt.
"""
from fastapi import HTTPException, Request
from urllib.parse import urlsplit

# Nur Verfahren, die etwas verändern. Ein GET ändert nichts, und die fremde
# Seite bekommt die Antwort ohnehin nicht zu sehen.
_SCHREIBENDE_VERFAHREN = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def pruefe_herkunft(request: Request) -> None:
    if request.method not in _SCHREIBENDE_VERFAHREN:
        return

    origin = request.headers.get("origin")
    if not origin:
        return

    # Verglichen wird gegen den `Host`-Kopf, nicht gegen eine feste Adresse:
    # die Oberfläche ist unter localhost:3000, 127.0.0.1:3000 und je nach
    # Aufstellung hinter einem eigenen Namen erreichbar. Maßgeblich ist, dass
    # die Seite, die sendet, dieselbe ist wie die, die antwortet.
    if urlsplit(origin).netloc == request.headers.get("host"):
        return

    raise HTTPException(
        403,
        "Diese Anfrage kam von einer fremden Webseite und wurde deshalb nicht "
        "ausgeführt. Öffnen Sie das Programm direkt in einem eigenen "
        "Browser-Tab und versuchen Sie es dort erneut.",
    )
