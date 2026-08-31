"""Empfängerlisten für die Kopie der Rechnungsmail (#58).

Die Kopie geht durch drei Formulare: Kundenstamm, Einstellungen, Sende-Dialog.
Überall ist die Eingabe derselbe freie Text, und überall muss daraus dieselbe
Liste werden. Deshalb liegt die Zerlegung hier und nicht dreimal in den Routern:
drei Kopien derselben Regel laufen auseinander, und die Abweichung fällt erst
auf, wenn eine Rechnung bei jemandem landet, der sie nicht bekommen sollte.

Bewusst kein `email-validator` als Abhängigkeit: geprüft wird die Form, nicht die
Erreichbarkeit. Ob die Adresse zustellbar ist, weiß erst der Mailserver, und die
Antwort darauf steht im Versandprotokoll (`InvoiceSendLog.error`).
"""
import re

# Fünf Adressen sind großzügig für den Fall, für den das gebaut wurde (zwei bis
# drei Zuständige beim Kunden). Die Grenze steht nicht gegen Missbrauch, sondern
# gegen den Vertipper, der eine ganze Adressliste in das Feld kippt.
GRENZE_ANZAHL = 5

# Die Spalten `customers.cc_emails`, `app_config.invoice_cc_email` und
# `invoice_send_log.cc_email` fassen 500 Zeichen. Ohne Prüfung hier bräche der
# Versand erst beim Schreiben des Protokolls ab, also nachdem die Mail draußen
# ist: gesendet, aber nicht nachweisbar.
GRENZE_LAENGE = 500

_TRENNER = re.compile(r"[,;]")

# Form, nicht Norm: ein Zeichen vor dem @, eines danach, ein Punkt mit mindestens
# zwei Buchstaben am Ende. Trennzeichen und Leerraum sind ausgeschlossen, sonst
# rutschte eine unzerlegte Liste als eine „Adresse" durch.
_ADRESSE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[A-Za-z]{2,}$")


def zerlege(text: str | None, *, ohne: str | None = None) -> list[str]:
    """Freien Text in eine Adressliste zerlegen.

    Trennt an Komma und Strichpunkt, entfernt Leerraum und leere Stücke und wirft
    Wiederholungen ohne Rücksicht auf Groß- und Kleinschreibung weg. Die
    Reihenfolge der Eingabe bleibt: die erste Adresse ist in aller Regel die des
    Hauptansprechpartners, und eine Sortierung würde diese Aussage stillschweigend
    verwerfen.

    `ohne` streicht eine Adresse aus dem Ergebnis, im Regelfall die des
    Empfängers. Wer im An-Feld steht, braucht keine Kopie an sich selbst.
    """
    if not text:
        return []
    gestrichen = (ohne or "").strip().lower()
    gesehen: set[str] = set()
    adressen: list[str] = []
    for stueck in _TRENNER.split(text):
        adresse = stueck.strip()
        if not adresse:
            continue
        schluessel = adresse.lower()
        if schluessel in gesehen or schluessel == gestrichen:
            continue
        gesehen.add(schluessel)
        adressen.append(adresse)
    return adressen


def pruefe(text: str | None) -> str | None:
    """Gibt eine Meldung zurück, wenn die Eingabe unbrauchbar ist, sonst None.

    Leer ist zulässig: „keine Kopie" ist ein Wunsch, kein Eingabefehler.
    """
    adressen = zerlege(text)
    if not adressen:
        return None
    for adresse in adressen:
        if not _ADRESSE.match(adresse):
            return f"Keine gültige E-Mail-Adresse: {adresse}"
    if len(adressen) > GRENZE_ANZAHL:
        return f"Höchstens {GRENZE_ANZAHL} Adressen in Kopie."
    if len(formatiere(adressen)) > GRENZE_LAENGE:
        return f"Die Liste ist zu lang (höchstens {GRENZE_LAENGE} Zeichen)."
    return None


def formatiere(adressen) -> str:
    """Kanonische Schreibweise für Datenbank und Mailkopf."""
    return ", ".join(adressen)


def normalisiere(text: str | None, *, ohne: str | None = None) -> str:
    """Freien Text in die Form bringen, die gespeichert und versendet wird."""
    return formatiere(zerlege(text, ohne=ohne))
