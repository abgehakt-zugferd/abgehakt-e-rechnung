#!/bin/sh
# Was Datenwache und ihre Testsuite tun, wenn mktemp scheitert.
#
# Anlass (2026-10-06, gemessen in einer Schwesterkopie dieser Wache): In einer
# Sandbox scheiterte `mktemp` ohne Vorlage, weil es $TMPDIR uebergeht. Zwei
# Folgen, beide still:
#   1. Die Wache schrieb ihre Befunde nach "" und meldete rc=0. Ein Push mit
#      IBAN, .env oder privatem Schluessel ging durch.
#   2. Die Suite bekam eine leere Werkstatt, und `git -C "" commit` lief im
#      UMGEBENDEN Repositorium. Dort, wo ein Commit-Hook die Suite startet, ergab
#      das eine Prozessschleife bis zum Prozesslimit des Rechners.
#
# Gemessen wird von aussen: Jedes Skript laeuft in einer Wegwerf-Huelle (ein Repo
# ohne Hooks, mit gestagter Arbeit), mktemp ist eine Attrappe. Verlangt: Abbruch
# mit dem Wortlaut GENAU DES Riegels, der greifen soll, und die Huelle bleibt
# unberuehrt. Der Wortlaut ist je Riegel eindeutig, sonst haelt ein zweiter
# Riegel den Fall gruen, waehrend der gemeinte fehlt.
#
# Diesen Test nie ohne Huelle umbauen: dann ist das echte Repo die Huelle.

set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_COMMON_DIR GIT_NAMESPACE GIT_QUARANTINE_PATH

hier=$(cd "$(dirname "$0")" && pwd)
fehl=0
leer=0000000000000000000000000000000000000000

basis=$(mktemp -d "${TMPDIR:-/tmp}/werkstattprobe.XXXXXX") && [ -d "$basis" ] || {
    echo "test_werkstatt: eigene Werkstatt nicht anlegbar - nichts gemessen." >&2
    exit 2
}
trap 'rm -rf "$basis"' EXIT
echtes_mktemp=$(command -v mktemp)

# Attrappen. "immer": scheitert bei jedem Aufruf. "repo": nur an der Vorlage
# repo.* (Werkstatt entsteht, Wegwerf-Repo nicht). "ab2": der erste Aufruf
# gelingt, jeder weitere scheitert (erste Ablage ja, zweite nein).
attrappe() {
    mkdir -p "$basis/bin-$1"
    {
        echo '#!/bin/sh'
        case "$1" in
            immer) echo 'echo "mktemp: Attrappe scheitert" >&2; exit 1' ;;
            repo)  echo 'case "$*" in *repo.*) echo "mktemp: Attrappe scheitert" >&2; exit 1;; esac' ;;
            ab2)   echo "z=\"$basis/zaehler\"; n=\$(cat \"\$z\" 2>/dev/null || echo 0); echo \$((n+1)) > \"\$z\"" ;
                   echo '[ "$n" -ge 1 ] && { echo "mktemp: Attrappe scheitert" >&2; exit 1; }' ;;
        esac
        echo "exec \"$echtes_mktemp\" \"\$@\""
    } > "$basis/bin-$1/mktemp"
    chmod +x "$basis/bin-$1/mktemp"
}
attrappe immer; attrappe repo; attrappe ab2
mkdir "$basis/keine-hooks"

# Huelle mit gestagter Arbeit: Erst damit hat ein verirrtes `git commit` etwas
# zu committen.
huelle="$basis/huelle"
mkdir "$huelle"
git -C "$huelle" init -q
git -C "$huelle" config core.hooksPath "$basis/keine-hooks"
git -C "$huelle" config user.name huelle
git -C "$huelle" config user.email huelle@example.invalid
ist=$(git -C "$huelle" rev-parse --absolute-git-dir)
[ "$ist" = "$(cd "$huelle" && pwd -P)/.git" ] || {
    echo "test_werkstatt: Huelle zeigt auf $ist - nichts gemessen." >&2
    exit 2
}

# Ein Commit mit einer USt-IdNr-artigen Folge (zur Laufzeit zusammengesetzt, damit
# diese Datei selbst sauber bleibt). Nur er fuehrt in die zweite Ablage.
_p1="DE"; _p2="815739204"
printf 'probe %s%s ende\n' "$_p1" "$_p2" > "$huelle/ust.txt"
git -C "$huelle" add ust.txt
git -C "$huelle" commit -qm probe
ust_commit=$(git -C "$huelle" rev-parse HEAD)
printf 'gestagt\n' > "$huelle/vorgemerkt.txt"
git -C "$huelle" add vorgemerkt.txt

# $1 Name  $2 Attrappe  $3 Skript  $4 Wortlaut des Riegels  [$5 stdin-Zeile]
pruefe_abbruch() {
    aus="$basis/$1.aus"
    rm -f "$basis/zaehler"
    git -C "$huelle" config user.name huelle
    vorher=$(git -C "$huelle" rev-list --all --count)
    ( cd "$huelle" && printf '%s\n' "${5:-}" \
        | PATH="$basis/bin-$2:$PATH" ZEMP_ECHTDATEN_MUSTER=/nicht/da sh "$3" ) > "$aus" 2>&1
    rc=$?
    neu=$(( $(git -C "$huelle" rev-list --all --count) - vorher ))
    autor=$(git -C "$huelle" config --get user.name)
    if [ "$rc" -ne 0 ] && grep -qF -- "$4" "$aus" \
        && [ "$neu" -eq 0 ] && [ "$autor" = "huelle" ]; then
        echo "gruen $1"
    else
        echo "ROT   $1 (rc=$rc, neue Commits=$neu, user.name=$autor)"
        sed 's/^/      /' "$aus" | tail -5
        fehl=1
    fi
}

pruefe_abbruch suite_ohne_werkstatt_bricht_ab immer \
    "$hier/test_datenwache.sh" "keine Werkstatt anlegbar"
pruefe_abbruch suite_ohne_wegwerfrepo_bricht_ab repo \
    "$hier/test_datenwache.sh" "ausserhalb der Werkstatt"
pruefe_abbruch wache_ohne_befundablage_sperrt immer \
    "$hier/datenwache.sh" "keine Befundablage anlegbar" \
    "refs/heads/probe $ust_commit refs/heads/probe $leer"
pruefe_abbruch wache_ohne_zweite_ablage_sperrt ab2 \
    "$hier/datenwache.sh" "keine Zwischenablage anlegbar" \
    "refs/heads/probe $ust_commit refs/heads/probe $leer"

[ "$fehl" -eq 0 ] && echo "test_werkstatt: alle gruen"
exit $fehl
