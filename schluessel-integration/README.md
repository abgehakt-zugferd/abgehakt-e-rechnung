# Probeschlüssel der Ketten-Testinstanz

Nur öffentliche Schlüssel (`.pub`) und ihre Beiblätter (`.json`), und nur
**Probeschlüssel**: am Namen erkennbar (`-probe-`).

Dieser Ordner steht neben `backend/schluessel/` und nicht darin, aus einem Grund:
`backend/` wandert ins Auslieferungsabbild. Ein Probeschlüssel, der dort läge,
wäre auf jeder fremden Installation dabei. Die Testinstanz hängt diesen Ordner
statt dessen ein (`docker-compose.integration.yml`).

Die zweite Hälfte derselben Zusage steht im Programm: einen Schlüssel mit
`-probe-` im Namen nimmt eine Installation nur an, wenn sie als Testinstanz
läuft (`INSTALLATION_MODE=testinstanz`, siehe `services/uebergabe_schluessel.py`).
Der Ordner ist nicht in Git; sein Inhalt kommt aus den Übergabepapieren.
