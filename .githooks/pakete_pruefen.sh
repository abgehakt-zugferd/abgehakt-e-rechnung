#!/usr/bin/env bash
# Schwachstellenpruefung der Python-Pakete gegen backend/uv.lock.
#
# Aufrufer ist .github/workflows/pip-audit.yml; das Skript liegt hier, damit es
# einen eigenen Shell-Test hat (test_pakete_pruefen.sh) und der Workflow nur noch
# aufruft. Lokal geht es genauso: `.githooks/pakete_pruefen.sh` (braucht uv, pip-audit
# und python3 auf PATH).
#
# Gemessen wird in zwei Laeufen, getrennt gemeldet:
#   Laufzeit  die Pakete, die ins Abbild kommen (`uv sync --no-group test`)
#   Test      nur die Gruppe "test" (pytest und Begleiter): laeuft in CI und bei
#             Entwicklern, nicht beim Anwender; eine Luecke dort ist weniger dringend,
#             aber sichtbar.
# Der Export ist hashgesichert (`--require-hashes`): pip-audit baut dann kein eigenes
# venv und loest nichts auf, es fragt nur zu genau den Fassungen der Lock-Datei nach.
# Plattformmarker (`; sys_platform == 'win32'`) werden vorher entfernt: sonst liesse
# pip-audit Pakete der jeweils anderen Plattform lautlos aus, und die Pruefung sagte
# auf einem Linux-Runner nichts ueber Windows-Pakete.
#
# "Nicht gemessen" ist nie gruen. Fehlt uv.lock, uv, pip-audit, python3, die
# Ausnahmendatei oder die Ausgabe, oder sind es null Pakete, oder weniger geprueft als
# gepinnt: Exit 1 mit "NICHT GEMESSEN" und dem Grund. Ein Fund ist ebenfalls Exit 1.
#
# Ausnahmen (.github/pip-audit-ausnahmen.txt): Format und Regeln stehen im Kopf dieser
# Datei. Das Skript prueft Vollstaendigkeit und Ablauf und reicht nur gueltige Kennungen
# per --ignore-vuln an pip-audit weiter; pip-audit selbst kennt kein Ablaufdatum.
#
# Umgebung (fuer Tests): PAKETE_WURZEL (Repo-Wurzel), PAKETE_HEUTE (JJJJ-MM-TT).
set -uo pipefail
set -f

wurzel="${PAKETE_WURZEL:-$(cd "$(dirname "$0")/.." && pwd)}"
heute="${PAKETE_HEUTE:-$(date +%Y-%m-%d)}"
lock="$wurzel/backend/uv.lock"
ausnahmen="$wurzel/.github/pip-audit-ausnahmen.txt"

werkstatt=$(mktemp -d "${TMPDIR:-/tmp}/pakete.XXXXXX") && [ -d "$werkstatt" ] || {
    echo "NICHT GEMESSEN: keine Werkstatt anlegbar (mktemp)." >&2
    exit 1
}
trap 'rm -rf "$werkstatt"' EXIT

ungemessen() {
    echo "ROT: NICHT GEMESSEN: $1" >&2
    [ -n "${GITHUB_ACTIONS:-}" ] && echo "::error::NICHT GEMESSEN: $1"
    exit 1
}

[ -f "$lock" ] || ungemessen "backend/uv.lock fehlt."
[ -f "$wurzel/backend/pyproject.toml" ] || ungemessen "backend/pyproject.toml fehlt."
command -v uv >/dev/null 2>&1 || ungemessen "uv ist nicht installiert (nicht auf PATH)."
command -v pip-audit >/dev/null 2>&1 || ungemessen "pip-audit ist nicht installiert (nicht auf PATH)."
command -v python3 >/dev/null 2>&1 || ungemessen "python3 fehlt (Auswertung der Ausgabe)."
[ -f "$ausnahmen" ] || ungemessen ".github/pip-audit-ausnahmen.txt fehlt (leere Datei genuegt, aber sie muss da sein)."

# --- Ausnahmen lesen: Kennung, Issue-Nummer, Ablaufdatum --------------------------
ignorieren=()
ausnahmefehler=0
nr=0
while IFS= read -r zeile || [ -n "$zeile" ]; do
    nr=$((nr + 1))
    zeile="${zeile#"${zeile%%[![:space:]]*}"}"
    case "$zeile" in ''|'#'*) continue ;; esac
    # shellcheck disable=SC2086
    set -- $zeile
    if [ "$#" -ne 3 ]; then
        echo "ROT: Ausnahme unvollständig (Zeile $nr): erwartet 'Kennung Issue Ablaufdatum', gefunden: $zeile" >&2
        ausnahmefehler=1
        continue
    fi
    kennung=$1 issue=$2 ablauf=$3
    printf '%s' "$kennung" | grep -Eq '^[A-Za-z0-9][A-Za-z0-9_.-]*$' || {
        echo "ROT: Ausnahme Zeile $nr: Kennung '$kennung' ist keine gueltige Kennung." >&2
        ausnahmefehler=1; continue; }
    printf '%s' "$issue" | grep -Eq '^#?[0-9]+$' || {
        echo "ROT: Ausnahme Zeile $nr ($kennung): Issue '$issue' ist keine Nummer (z. B. #123)." >&2
        ausnahmefehler=1; continue; }
    printf '%s' "$ablauf" | grep -Eq '^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$' || {
        echo "ROT: Ausnahme Zeile $nr ($kennung): Datum '$ablauf' ist nicht JJJJ-MM-TT." >&2
        ausnahmefehler=1; continue; }
    if [[ "$ablauf" < "$heute" ]]; then
        echo "ROT: Ausnahme abgelaufen (Zeile $nr): $kennung, Issue $issue, Ablauf $ablauf, heute $heute. Paket aktualisieren oder im Issue neu begruenden." >&2
        ausnahmefehler=1; continue
    fi
    ignorieren+=(--ignore-vuln "$kennung")
done < "$ausnahmen"
[ "$ausnahmefehler" -eq 0 ] || exit 1

# --- ein Lauf: Export, Zaehlen, pip-audit, Auswerten ------------------------------
# $1 Name  $2.. Gruppenschalter fuer uv export. Setzt gepruefte_$1 nicht global,
# sondern gibt die Zahl in $werkstatt/zahl.$1 ab (kein Unterprozess-Verlust).
fund=0
lauf() {
    name=$1; shift
    exp="$werkstatt/$name.txt"
    if ! ( cd "$wurzel/backend" && uv export --frozen --format requirements-txt \
            --no-emit-project --no-header --no-annotate "$@" ) > "$exp.roh" 2> "$werkstatt/$name.uv.err"; then
        ungemessen "uv export ($name) ist gescheitert: $(tr '\n' ' ' < "$werkstatt/$name.uv.err")"
    fi
    sed 's/^\([A-Za-z0-9_.-]*==[^ ]*\) ; .* \\$/\1 \\/' "$exp.roh" > "$exp"
    gepinnt=$(grep -cE '^[A-Za-z0-9_.-]+==' "$exp")
    [ "$gepinnt" -gt 0 ] || ungemessen "Export ($name) enthaelt kein einziges gepinntes Paket."

    pip-audit --require-hashes --disable-pip --format json \
        ${ignorieren[@]+"${ignorieren[@]}"} -r "$exp" \
        > "$werkstatt/$name.json" 2> "$werkstatt/$name.pa.err"
    pa_rc=$?
    auswertung=$(python3 -I "$(dirname "$0")/pakete_auswerten.py" auswerten "$werkstatt/$name.json" "$exp")
    py_rc=$?
    [ "$py_rc" -eq 0 ] || ungemessen "pip-audit ($name): Auswertung ist gescheitert (rc=$py_rc): $(printf '%s' "$auswertung" | tr '\n' ' ' | cut -c1-300)"
    nicht_geprueft=$(printf '%s\n' "$auswertung" | sed -n 's/^UNGEMESSEN //p')
    [ -z "$nicht_geprueft" ] || ungemessen "pip-audit ($name): $(printf '%s' "$nicht_geprueft" | tr '\n' ';')"
    geprueft=$(printf '%s\n' "$auswertung" | sed -n 's/^ANZAHL //p')
    [ "${geprueft:-0}" -gt 0 ] || ungemessen "pip-audit ($name) hat null Pakete geprueft."
    [ "$geprueft" -eq "$gepinnt" ] || ungemessen "pip-audit ($name) hat $geprueft Pakete geprueft, gepinnt sind $gepinnt."
    # pip-audit meldet dieselbe Kennung je Alias mehrfach: einmal je Zeile genuegt.
    funde=$(printf '%s\n' "$auswertung" | sed -n 's/^FUND //p' | sort -u)
    if [ -n "$funde" ]; then
        printf 'ROT: Fund in %s:\n' "$name" >&2
        printf '%s\n' "$funde" | sed 's/^/  /' >&2
        fund=1
    elif [ "$pa_rc" -ne 0 ]; then
        ungemessen "pip-audit ($name) endete mit rc=$pa_rc ohne Fund: $(tr '\n' ' ' < "$werkstatt/$name.pa.err" | cut -c1-300)"
    fi
    zahlen+=("$name $geprueft Pakete")
}

zahlen=()
lauf Laufzeit --no-group test
lauf Test --only-group test

[ "$fund" -eq 0 ] || exit 1
echo "OK: ${zahlen[0]}, ${zahlen[1]} gegen backend/uv.lock geprueft, keine bekannten Luecken (Ausnahmen: $(( ${#ignorieren[@]} / 2 )))."
