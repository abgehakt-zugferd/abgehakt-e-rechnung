#!/bin/sh
# Datenwache (pre-push): prueft ausgehende Commits auf Muster echter Daten (#49).
#
# Massgebliche Vorlage: zemp-integration/werkzeuge/datenwache/pre-push-datenwache.sh
#
# Was geprueft wird (nur NEU hinzukommende Zeilen der gepushten Commits):
#   - private Schluessel (BEGIN ... PRIVATE KEY)
#   - IBAN-Format (Registry-Laender, Laenge aus iban_laengen.tsv, MOD 97-10;
#     Ausnahme: BBAN = PROBE + nur Nullen, Issue #93)
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
#
# Issue #93: IBAN laenderuebergreifend ueber awk (kein Python, kein bc).
# Laengentabelle: backend/app/data/iban_laengen.tsv (dieselbe Quelle wie die
# Anwendung). Unbekannte Praefixe, falsche Laenge und MOD-97-Rest != 1 sind
# kein Befund. Fixture-Form PROBE+Nullen (wie probe_daten.py) wird ausgenommen.

set -u

leer=0000000000000000000000000000000000000000

# Laengentabelle relativ zum Hook-Skript (nicht zum cwd: Tests laufen in Wegwerf-Repos).
_dw_home=$(CDPATH= cd "$(dirname "$0")" && pwd)
iban_laengen_tsv="$_dw_home/../backend/app/data/iban_laengen.tsv"

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

# IBAN laenderuebergreifend: Laengentabelle + MOD 97-10 in awk (Issue #93).
# stdin = Diff-Zeilen. Exit von awk unverfaelscht (keine Pipe hinter awk).
pruefe_iban_format() {
    commit=$1
    if [ ! -f "$iban_laengen_tsv" ]; then
        printf '%s | %s\n%s\n' "$commit" "IBAN-Format" \
            "1:datenwache: Laengentabelle fehlt: $iban_laengen_tsv" >> "$befunde"
        return 0
    fi
    treffer=""
    awk_ec=0
    treffer=$(awk -v laengen_datei="$iban_laengen_tsv" '
        BEGIN {
            while ((getline z < laengen_datei) > 0) {
                if (z ~ /^#/ || z ~ /^[[:space:]]*$/) continue
                split(z, teile, "\t")
                if (teile[1] != "" && teile[2] != "")
                    laenge[teile[1]] = teile[2] + 0
            }
            close(laengen_datei)
            buchstaben = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        }
        function ist_alnum(c) { return c ~ /[A-Za-z0-9]/ }
        function ist_trenn(c) { return c == " " || c == "\t" }
        function zufuehren(d) { rest = (rest * 10 + d) % 97 }
        function mod97_ok(iban,    umg, i, c, n) {
            umg = substr(iban, 5) substr(iban, 1, 4)
            rest = 0
            for (i = 1; i <= length(umg); i++) {
                c = substr(umg, i, 1)
                if (c ~ /[0-9]/)
                    zufuehren(c + 0)
                else {
                    n = index(buchstaben, c) + 9
                    if (n < 10) return 0
                    zufuehren(int(n / 10))
                    zufuehren(n % 10)
                }
            }
            return rest == 1
        }
        function ist_probe_fixture(iban,    bban) {
            bban = substr(iban, 5)
            return bban ~ /^PROBE0+$/
        }
        function versuche_ab(start,    j, ch, gesammelt, praefix, erl) {
            gesammelt = ""
            j = start
            while (j <= length(zeile) && length(gesammelt) < 4) {
                ch = substr(zeile, j, 1)
                if (ist_alnum(ch)) {
                    gesammelt = gesammelt toupper(ch)
                    j++
                } else if (ist_trenn(ch) && length(gesammelt) > 0) {
                    j++
                } else {
                    return 0
                }
            }
            if (length(gesammelt) < 4) return 0
            if (gesammelt !~ /^[A-Z]{2}[0-9]{2}/) return 0
            praefix = substr(gesammelt, 1, 2)
            if (!(praefix in laenge)) return 0
            erl = laenge[praefix]
            while (j <= length(zeile) && length(gesammelt) < erl) {
                ch = substr(zeile, j, 1)
                if (ist_alnum(ch)) {
                    gesammelt = gesammelt toupper(ch)
                    j++
                } else if (ist_trenn(ch)) {
                    j++
                } else {
                    return 0
                }
            }
            if (length(gesammelt) != erl) return 0
            if (j <= length(zeile) && ist_alnum(substr(zeile, j, 1))) return 0
            if (!mod97_ok(gesammelt)) return 0
            if (ist_probe_fixture(gesammelt)) return 0
            return 1
        }
        {
            zeile = $0
            n = length(zeile)
            for (i = 1; i <= n; i++) {
                ch = substr(zeile, i, 1)
                if (ch !~ /[A-Za-z]/) continue
                if (i > 1 && ist_alnum(substr(zeile, i - 1, 1))) continue
                if (versuche_ab(i)) {
                    printf "%d:%s\n", NR, zeile
                    next
                }
            }
        }
    ') || awk_ec=$?
    if [ "$awk_ec" -ne 0 ]; then
        printf '%s | %s\n%s\n' "$commit" "IBAN-Format" \
            "1:datenwache: awk-IBAN-Pruefung fehlgeschlagen (exit $awk_ec)" >> "$befunde"
        return 0
    fi
    if [ -n "$treffer" ]; then
        printf '%s | %s\n%s\n' "$commit" "IBAN-Format" "$treffer" >> "$befunde"
    fi
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
        printf '%s\n' "$zeilen" | pruefe_iban_format "$c"
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
