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
#
# Issue #88: Treffer der USt-/Steuernummer-Grobmuster mit erkennbarer
# Konstruktionsfolge (aufsteigend, absteigend oder gleiche Ziffer, jeweils mit
# Umbruch 9->0) werden durchgelassen. Das ist eine bewusste Aufweichung: die
# Wache wird um genau 90 Zeichenketten blinder (30 Folgen je Laenge 9, 10 und
# 11; Wahrscheinlichkeit, dass eine echte USt-IdNr. darunterfaellt: rund 30 zu
# einer Milliarde). Die Grobmuster selbst bleiben unveraendert; die Regel
# entscheidet nur ueber ihre Treffer. Laengen folgen den Grobmustern (USt:
# immer 9; Steuernummer: Ziffernzahl nach Entfernen der Schraegstriche), nicht
# einer Ausnahmeliste und nicht dem Dateipfad.

set -u

leer=0000000000000000000000000000000000000000

if [ "${DATENWACHE_UEBERSTIMMT:-0}" = "1" ]; then
    echo "datenwache: UEBERSTIMMT - Pruefung uebersprungen." >&2
    exit 0
fi

muster_datei="${ZEMP_ECHTDATEN_MUSTER:-$HOME/.zemp/echtdaten-muster.txt}"
befunde=$(mktemp)
trap 'rm -f "$befunde"' EXIT

# Erzeugt eine Ziffernfolge: Startziffer $1, Schritt $2 (+1/-1/0), Laenge $3.
# Schritt wrappt ueber % 10 (9+1 -> 0). POSIX-Arithmetik, kein grep -P.
ziffernfolge() {
    i=0
    s=""
    while [ "$i" -lt "$3" ]; do
        s="$s$(( ( $1 + i * $2 + 100 ) % 10 ))"
        i=$(( i + 1 ))
    done
    printf '%s' "$s"
}

# 0 = konstruierte Folge (Fixture-tauglich), 1 = nicht.
ist_konstruiert() {
    [ -z "$1" ] && return 1
    laenge=${#1}
    d=0
    while [ "$d" -le 9 ]; do
        [ "$(ziffernfolge "$d" 1 "$laenge")" = "$1" ] && return 0
        [ "$(ziffernfolge "$d" -1 "$laenge")" = "$1" ] && return 0
        [ "$(ziffernfolge "$d" 0 "$laenge")" = "$1" ] && return 0
        d=$(( d + 1 ))
    done
    return 1
}

pruefe() {
    treffer=$(grep -nE -- "$2" 2>/dev/null) || return 0
    printf '%s | %s\n%s\n' "$3" "$1" "$treffer" >> "$befunde"
}

# Wie pruefe, aber Zeilen nur melden, wenn mindestens ein Treffer von $2
# Ziffern enthaelt, die NICHT konstruiert sind. $4 = ERE zum Herausschneiden
# der Rohform (z. B. DE123456789 oder 12/345/67890), $5 = sed, der daraus
# nur die Ziffern macht.
pruefe_ausser_konstruiert() {
    name=$1
    muster=$2
    commit=$3
    roh_ere=$4
    ziffern_sed=$5
    treffer=$(grep -nE -- "$muster" 2>/dev/null) || return 0
    echt=$(mktemp)
    printf '%s\n' "$treffer" | while IFS= read -r zeile; do
        [ -z "$zeile" ] && continue
        inhalt=${zeile#*:}
        hat_echte=0
        for roh in $(printf '%s\n' "$inhalt" | grep -oE -- "$roh_ere"); do
            ziffern=$(printf '%s' "$roh" | sed -E "$ziffern_sed")
            if ! ist_konstruiert "$ziffern"; then
                hat_echte=1
                break
            fi
        done
        [ "$hat_echte" -eq 1 ] && printf '%s\n' "$zeile" >> "$echt"
    done
    if [ -s "$echt" ]; then
        printf '%s | %s\n' "$commit" "$name" >> "$befunde"
        cat "$echt" >> "$befunde"
    fi
    rm -f "$echt"
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
        printf '%s\n' "$zeilen" | pruefe_ausser_konstruiert "USt-IdNr-Format" \
            '(^|[^A-Za-z0-9])DE[0-9]{9}([^0-9]|$)' "$c" \
            'DE[0-9]{9}' 's/^DE//'
        printf '%s\n' "$zeilen" | pruefe_ausser_konstruiert "Steuernummer-Format" \
            '(^|[^0-9])[0-9]{2,3}/[0-9]{3}/[0-9]{4,5}([^0-9/]|$)' "$c" \
            '[0-9]{2,3}/[0-9]{3}/[0-9]{4,5}' 's/\///g'
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
