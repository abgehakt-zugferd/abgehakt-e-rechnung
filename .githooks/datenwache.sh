#!/bin/sh
# Datenwache (pre-push): prueft ausgehende Commits auf Muster echter Daten (#49).
#
# Massgebliche Vorlage: zemp-integration/werkzeuge/datenwache/pre-push-datenwache.sh
#
# Was geprueft wird (nur NEU hinzukommende Zeilen der gepushten Commits):
#   - private Schluessel (BEGIN ... PRIVATE KEY)
#   - IBAN-Format (DE, 22 Stellen, mit/ohne Leerzeichen)
#   - USt-IdNr-Format (DE + 9 Ziffern)
#   - Steuernummer-Format (NNN/NNN/NNNNN)
#   - neu hinzukommende .env-Dateien (ausser .env.example)
# Dazu optionale Zusatzmuster aus einer Datei AUSSERHALB des Repos:
#   ZEMP_ECHTDATEN_MUSTER (Vorgabe: ~/.zemp/echtdaten-muster.txt),
#   eine erweiterte Regex je Zeile, '#' beginnt einen Kommentar.
#   Fehlt die Datei, laufen nur die eingebauten Muster.
#
# Fund => Push bricht ab, mit Commit, Musterklasse und Zeile.
# Fehlalarm einmalig ueberstimmen: DATENWACHE_UEBERSTIMMT=1 git push

set -u

leer=0000000000000000000000000000000000000000

if [ "${DATENWACHE_UEBERSTIMMT:-0}" = "1" ]; then
    echo "datenwache: UEBERSTIMMT - Pruefung uebersprungen." >&2
    exit 0
fi

muster_datei="${ZEMP_ECHTDATEN_MUSTER:-$HOME/.zemp/echtdaten-muster.txt}"
befunde=$(mktemp)
trap 'rm -f "$befunde"' EXIT

pruefe() {
    treffer=$(grep -nE -- "$2" 2>/dev/null) || return 0
    printf '%s | %s\n%s\n' "$3" "$1" "$treffer" >> "$befunde"
}

while read -r _lokal_ref lokal_sha _fern_ref fern_sha; do
    [ "$lokal_sha" = "$leer" ] && continue
    if [ "$fern_sha" = "$leer" ]; then
        commits=$(git rev-list "$lokal_sha" --not --remotes)
    else
        commits=$(git rev-list "$fern_sha..$lokal_sha")
    fi

    for c in $commits; do
        env_neu=$(git show --format= --name-only --diff-filter=A "$c" \
            | grep -E '(^|/)\.env(\.[^/]*)?$' | grep -vE '\.env\.example$') \
            && printf '%s | .env-Datei\n%s\n' "$c" "$env_neu" >> "$befunde"

        zeilen=$(git show --format= --unified=0 "$c" | grep -E '^\+[^+]' | cut -c2-)
        [ -z "$zeilen" ] && continue

        printf '%s\n' "$zeilen" | pruefe "privater Schluessel" \
            '-----BEGIN [A-Z ]*PRIVATE KEY-----' "$c"
        printf '%s\n' "$zeilen" | pruefe "IBAN-Format" \
            'DE[0-9]{2} ?([0-9]{4} ?){4}[0-9]{2}' "$c"
        printf '%s\n' "$zeilen" | pruefe "USt-IdNr-Format" \
            '(^|[^A-Za-z0-9])DE[0-9]{9}([^0-9]|$)' "$c"
        printf '%s\n' "$zeilen" | pruefe "Steuernummer-Format" \
            '(^|[^0-9])[0-9]{2,3}/[0-9]{3}/[0-9]{4,5}([^0-9/]|$)' "$c"

        if [ -f "$muster_datei" ]; then
            grep -vE '^[[:space:]]*(#|$)' "$muster_datei" | while IFS= read -r m; do
                printf '%s\n' "$zeilen" | pruefe "Zusatzmuster" "$m" "$c"
            done
        fi
    done
done

if [ -s "$befunde" ]; then
    echo "" >&2
    echo "datenwache: Push abgebrochen - Muster echter Daten gefunden:" >&2
    echo "" >&2
    cat "$befunde" >&2
    echo "" >&2
    echo "In Repos und Issues gehoeren nur erfundene Testdaten (Namensregel: probe)." >&2
    echo "Fehlalarm? Einmalig ueberstimmen mit: DATENWACHE_UEBERSTIMMT=1 git push" >&2
    exit 1
fi

exit 0
