#!/bin/sh
# Charakterisierungstest fuer die Wurzelaufloesung in pre-push.
#
# Zeile 20 lautete `cd "$(git rev-parse --show-toplevel)"` — ohne Waechter.
# Scheitert rev-parse, ist die Kommandoersetzung leer, und `cd ""` gibt in bash
# Exit 0 zurueck, ohne das Verzeichnis zu wechseln. Der Hook lief dann im
# Aufrufverzeichnis weiter, statt abzubrechen.
#
# Geprueft wird nicht der Exit-Code allein — der waere auch ohne Waechter von
# 0 verschieden, weil die nachfolgenden Wachen im falschen Verzeichnis nichts
# finden. Geprueft wird, dass nach der gescheiterten Aufloesung NICHTS MEHR
# LAEUFT: die Attrappe der Datenwache hinterlaesst sonst ihre Spur.

set -u

hier=$(cd "$(dirname "$0")" && pwd)
hook="$hier/pre-push"
fehl=0
werkstatt=$(mktemp -d)
trap 'rm -rf "$werkstatt"' EXIT

# Ein Spiegel, der KEIN Repo ist: nur so scheitert rev-parse noch, nachdem der
# unset-Block die geerbten GIT_-Variablen abgeraeumt hat.
spiegel="$werkstatt/kein-repo"
mkdir -p "$spiegel/.githooks"
cp "$hook" "$spiegel/.githooks/pre-push"
chmod +x "$spiegel/.githooks/pre-push"
for attrappe in datenwache.sh wachen.sh; do
    printf '#!/bin/sh\ntouch "%s/spur.%s"\nexit 0\n' "$werkstatt" "$attrappe" \
        > "$spiegel/.githooks/$attrappe"
    chmod +x "$spiegel/.githooks/$attrappe"
done

aus=$( cd "$spiegel" && GIT_CEILING_DIRECTORIES="$werkstatt" \
       bash .githooks/pre-push probe probe </dev/null 2>&1 )
rc=$?

if [ "$rc" -eq 0 ]; then
    echo "ROT  Waechter: rc=0, erwartet ungleich 0" >&2; echo "$aus" >&2; fehl=1
else
    echo "gruen Waechter: bricht ab (rc=$rc)"
fi

for attrappe in datenwache.sh wachen.sh; do
    if [ -e "$werkstatt/spur.$attrappe" ]; then
        echo "ROT  $attrappe lief trotz gescheiterter Wurzelaufloesung" >&2
        echo "$aus" >&2; fehl=1
    else
        echo "gruen $attrappe lief nicht"
    fi
done

[ "$fehl" -eq 0 ] && echo "test_pre_push_waechter: alle gruen"
exit "$fehl"
