#!/bin/sh
# Umweg-Empfehlungs-Lint fuer test_pre_push_stand.sh (ausgelagert: 300-Zeilen-Grenze).
# Kein test_-Praefix, sonst liefe die Datei in jeder test_*.sh-Schleife als Test
# mit, der nichts prueft. Die Probe ueberspringt test_*- und *testhilfe.sh-Dateien:
# beide enthalten die Umweg-Muster als Testdaten, nicht als Empfehlung.

# $1 Ordner → Zeilen mit Umweg-Empfehlung (ohne reine Kommentare und ohne "nicht ...")
umweg_empfehlungen() {
    ordner=$1
    treffer_datei="$werkstatt/umweg-treffer.txt"
    : > "$treffer_datei"
    for f in "$ordner"/*.sh "$ordner"/pre-push; do
        [ -f "$f" ] || continue
        name=${f##*/}
        case "$name" in
            test_*|*testhilfe.sh) continue ;;
        esac
        grep -nH -E -- 'no-verify|hooksPath[ =]/dev/null|HUSKY=0' "$f" \
            >> "$treffer_datei" 2>/dev/null
    done
    grep -vE '^[^:]+:[0-9]+:[[:space:]]*#' "$treffer_datei" \
        | grep -vE 'nicht[^"]{0,12}(no-verify|hooksPath[ =]/dev/null|HUSKY=0)' || true
}

# $1 Name  $2 Dateiinhalt  $3 erwartet (rot=Empfehlung erkannt, gruen=kein Treffer)
pruefe_umweg_probe() {
    name=$1
    inhalt=$2
    erwartet=$3
    d="$werkstatt/probe-$name"
    mkdir -p "$d"
    printf '%s\n' "$inhalt" > "$d/hinweis.sh"
    fund=$(umweg_empfehlungen "$d")
    if [ "$erwartet" = rot ]; then
        if [ -n "$fund" ]; then
            echo "gruen $name"
        else
            echo "ROT  $name: Umweg-Empfehlung nicht erkannt" >&2
            fehl=1
        fi
    else
        if [ -z "$fund" ]; then
            echo "gruen $name"
        else
            echo "ROT  $name: Verbot als Umweg gewertet:" >&2
            printf '%s\n' "$fund" | sed 's/^/      /' >&2
            fehl=1
        fi
    fi
}
