#!/bin/sh
# Prueft NUR den Gleichlauf-Block in pre-push (nicht gleichlauf.py selbst).
#
# Wahl: Hook in einen Spiegel kopieren und mit Attrappen fuer die teure Suite
# bis zum Block laufen lassen. So steht der Block genau wie in pre-push unter
# Test, keine Abschrift. gleichlauf.py ist eine Attrappe unter PIPAUDIT_QUELLE.
#
# Kein Netz, kein echter claude-global-skills-Checkout.

set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_COMMON_DIR GIT_NAMESPACE GIT_QUARANTINE_PATH

hier=$(cd "$(dirname "$0")" && pwd)
fehl=0
zahl=0
leer=0000000000000000000000000000000000000000

werkstatt=$(mktemp -d "${TMPDIR:-/tmp}/gleichlauf-tor.XXXXXX") \
    && [ -n "$werkstatt" ] && [ -d "$werkstatt" ] || {
    echo "ABBRUCH: keine Werkstatt anlegbar (mktemp) - nichts gemessen." >&2
    exit 2
}
trap 'rm -rf "$werkstatt"' EXIT

# Spiegel mit eigenem .git, damit pipaudit.gleichlauf nicht vom umgebenden Klon kommt.
neues_repo() {
    d=$(mktemp -d "$werkstatt/repo.XXXXXX") && [ -n "$d" ] && [ -d "$d" ] || {
        echo "ABBRUCH: kein Wegwerf-Repo anlegbar." >&2
        exit 2
    }
    git -C "$d" init -q
    git -C "$d" config user.name probe
    git -C "$d" config user.email probe@example.invalid
    git -C "$d" config core.hooksPath "$werkstatt/keine-hooks"
    mkdir -p "$werkstatt/keine-hooks"
    mkdir -p "$d/.githooks/pip-audit-auswerter"
    cp "$hier/pre-push" "$d/.githooks/pre-push"
    chmod +x "$d/.githooks/pre-push"
    # Teure Suite: nur Spur, kein echter Lauf.
    printf '#!/bin/sh\ntouch "%s/spur.datenwache"\nexit 0\n' "$werkstatt" \
        > "$d/.githooks/datenwache.sh"
    printf '#!/bin/sh\ntouch "%s/spur.stand"\nexit 0\n' "$werkstatt" \
        > "$d/.githooks/pre-push-stand.sh"
    chmod +x "$d/.githooks/datenwache.sh" "$d/.githooks/pre-push-stand.sh"
    # Minimaler Commit, damit eine Ref-Zeile greift.
    printf 'probe\n' > "$d/README"
    git -C "$d" add README
    git -C "$d" commit -qm probe
    printf '%s\n' "$d"
}

# Attrappe: schreibt argv je Zeile, endet mit vorgegebenem Code.
schreib_attrappe() {
    q=$1
    code=$2
    mkdir -p "$q/pip-audit-auswerter"
    cat > "$q/pip-audit-auswerter/gleichlauf.py" <<ATT
import sys
open("$werkstatt/argv.txt", "w", encoding="utf-8").write("\\n".join(sys.argv[1:]) + "\\n")
sys.exit($code)
ATT
}

# $1 Name  $2 Repo  $3 Q  $4 Schalter (leer=unset, sonst Wert)  $5 erw_rc  $6 Wortlaut
# $7 Wortlaut-verboten (leer=keiner)  $8 suite_erwartet (0|1)  $9 HOME (leer=normal)
fall() {
    name=$1
    repo=$2
    q=$3
    schalter=$4
    erw_rc=$5
    wortlaut=$6
    verboten=${7:-}
    suite_erwartet=$8
    home_ort=${9:-}
    zahl=$((zahl + 1))
    rm -f "$werkstatt/spur.datenwache" "$werkstatt/spur.stand" "$werkstatt/argv.txt"
    if [ -n "$schalter" ]; then
        git -C "$repo" config --local pipaudit.gleichlauf "$schalter"
    else
        git -C "$repo" config --local --unset-all pipaudit.gleichlauf 2>/dev/null || true
    fi
    sha=$(git -C "$repo" rev-parse HEAD)
    aus="$werkstatt/$name.aus"
    if [ -n "$home_ort" ]; then
        env_q='PIPAUDIT_QUELLE='
        env_home="HOME=$home_ort"
    else
        env_q="PIPAUDIT_QUELLE=$q"
        env_home=
    fi
    ( cd "$repo" && printf 'refs/heads/main %s refs/heads/main %s\n' "$sha" "$leer" \
        | env $env_q $env_home bash .githooks/pre-push origin unused-url ) >"$aus" 2>&1
    rc=$?
    ok=1
    if [ "$rc" -ne "$erw_rc" ]; then
        ok=0
    fi
    [ -z "$wortlaut" ] || grep -qF -- "$wortlaut" "$aus" || ok=0
    [ -z "$verboten" ] || ! grep -qF -- "$verboten" "$aus" || ok=0
    if [ "$suite_erwartet" -eq 1 ]; then
        [ -e "$werkstatt/spur.datenwache" ] || ok=0
        [ -e "$werkstatt/spur.stand" ] || ok=0
    else
        [ ! -e "$werkstatt/spur.datenwache" ] || ok=0
        [ ! -e "$werkstatt/spur.stand" ] || ok=0
    fi
    if [ "$ok" -eq 1 ]; then
        echo "gruen $name"
    else
        echo "ROT  $name: rc=$rc (erwartet $erw_rc), suite_erwartet=$suite_erwartet" >&2
        sed 's/^/      /' "$aus" | tail -30 >&2
        fehl=1
    fi
}

repo=$(neues_repo)
# Physikalische Pfade: macOS liefert /var vs /private/var.
kopie=$(cd "$repo/.githooks/pip-audit-auswerter" && pwd -P)
q_mit=$(mktemp -d "$werkstatt/q-mit.XXXXXX")
q_mit=$(cd "$q_mit" && pwd -P)
q_leer=$(mktemp -d "$werkstatt/q-leer.XXXXXX")
q_leer=$(cd "$q_leer" && pwd -P)

# Attrappe 0 → Block laesst durch, Suite laeuft.
schreib_attrappe "$q_mit" 0
fall attrappe_0_laesst_durch "$repo" "$q_mit" "" 0 "" "" 1
# argv: Kopie-Verzeichnis und --checkout Q (Zeilen, Pfade physikalisch).
zahl=$((zahl + 1))
argv_ok=0
if [ -f "$werkstatt/argv.txt" ]; then
    z1=$(sed -n '1p' "$werkstatt/argv.txt")
    z2=$(sed -n '2p' "$werkstatt/argv.txt")
    z3=$(sed -n '3p' "$werkstatt/argv.txt")
    z1p=$(cd "$z1" 2>/dev/null && pwd -P)
    z3p=$(cd "$z3" 2>/dev/null && pwd -P)
    [ "$z1p" = "$kopie" ] && [ "$z2" = "--checkout" ] && [ "$z3p" = "$q_mit" ] && argv_ok=1
fi
if [ "$argv_ok" -eq 1 ]; then
    echo "gruen argv_enthaelt_kopie_und_checkout_q"
else
    echo "ROT  argv_enthaelt_kopie_und_checkout_q: $(cat "$werkstatt/argv.txt" 2>/dev/null)" >&2
    fehl=1
fi

# Attrappe 1 → rot, Suite nicht.
schreib_attrappe "$q_mit" 1
fall attrappe_1_ist_rot "$repo" "$q_mit" "" 1 "" "" 0

# Attrappe 2 → rot, Suite nicht.
schreib_attrappe "$q_mit" 2
fall attrappe_2_ist_rot "$repo" "$q_mit" "" 1 "" "" 0

# Attrappe 3 → rot, Suite nicht.
schreib_attrappe "$q_mit" 3
fall attrappe_3_ist_rot "$repo" "$q_mit" "" 1 "" "" 0

# Schalter pflicht bei vorhandener Quelle: Attrappe laeuft, ihr Exit zaehlt.
schreib_attrappe "$q_mit" 2
fall quelle_vorhanden_und_pflicht_nimmt_attrappen_exit "$repo" "$q_mit" "pflicht" 1 "" "" 0

# Attrappe fehlt, kein Schalter → WARNUNG und durch.
fall fehlt_ohne_schalter_warnung_und_durch "$repo" "$q_leer" "" 0 \
    "WARNUNG: Gleichlauf NICHT GEMESSEN" "ROT: Gleichlauf" 1

# Attrappe fehlt, Schalter pflicht → ROT.
fall fehlt_mit_pflicht_ist_rot "$repo" "$q_leer" "pflicht" 1 \
    "ROT: Gleichlauf NICHT GEMESSEN" "" 0

# Attrappe fehlt, Schalter anderer Wert → WARNUNG und durch.
fall fehlt_mit_anderem_schalter_warnung_und_durch "$repo" "$q_leer" "aus" 0 \
    "WARNUNG: Gleichlauf NICHT GEMESSEN" "ROT: Gleichlauf" 1

# Leere PIPAUDIT_QUELLE faellt auf \$HOME/Documents/... zurueck.
home_q="$werkstatt/home"
mkdir -p "$home_q/Documents/claude/claude-global-skills"
schreib_attrappe "$home_q/Documents/claude/claude-global-skills" 0
fall leere_quelle_nimmt_home_fallback "$repo" "__leere_quelle__" "" 0 "" "" 1 "$home_q"
zahl=$((zahl + 1))
fallback_argv_ok=0
if [ -f "$werkstatt/argv.txt" ]; then
    z3=$(sed -n '3p' "$werkstatt/argv.txt")
    z3p=$(cd "$z3" 2>/dev/null && pwd -P)
    ziel=$(cd "$home_q/Documents/claude/claude-global-skills" && pwd -P)
    [ "$z3p" = "$ziel" ] && fallback_argv_ok=1
fi
if [ "$fallback_argv_ok" -eq 1 ]; then
    echo "gruen leere_quelle_verwendet_home_als_checkout"
else
    echo "ROT  leere_quelle_verwendet_home_als_checkout: $(cat "$werkstatt/argv.txt" 2>/dev/null)" >&2
    fehl=1
fi

[ "$fehl" -eq 0 ] && echo "test_gleichlauf_tor: alle gruen ($zahl Faelle)"
exit "$fehl"
