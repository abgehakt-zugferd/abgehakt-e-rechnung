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

# --- Ausnahmen lesen: Kennung, Issue, Ablauf, seit -------------------------------
# Regeln und Meldungen stehen in pakete_auswerten.py (echter Kalendertag, Hoechstfrist
# ab seit, Ablauf). Hier nur der Ablauf: jede Meldung ist rot, jede Ausnahme des
# Pruefers ebenfalls.
py="$(dirname "$0")/pakete_auswerten.py"
ausnahme_aus=$(python3 -I "$py" ausnahmen "$ausnahmen" "$heute")
ausnahme_rc=$?
if [ "$ausnahme_rc" -ne 0 ]; then
    printf '%s\n' "$ausnahme_aus" | sed -n 's/^FEHLER /ROT: /p' >&2
    printf '%s\n' "$ausnahme_aus" | grep -q '^FEHLER ' \
        || ungemessen "Ausnahmendatei nicht auswertbar (rc=$ausnahme_rc): $(printf '%s' "$ausnahme_aus" | tr '\n' ' ' | cut -c1-300)"
    exit 1
fi
# Die Ausnahmen werden hier ausgewertet, nicht per `pip-audit --ignore-vuln`: pip-audit
# meldet nicht, ob eine Ausnahme etwas getroffen hat, und die Attrappe im Test kann den
# Aufruf dann exakt vergleichen.
ausnahme_ids=()
while read -r art kennung; do
    [ "$art" = "ID" ] && ausnahme_ids+=("$kennung")
done <<< "$ausnahme_aus"
benutzt=" "

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
        -r "$exp" \
        > "$werkstatt/$name.json" 2> "$werkstatt/$name.pa.err"
    pa_rc=$?
    auswertung=$(python3 -I "$py" auswerten "$werkstatt/$name.json" "$exp" ${ausnahme_ids[@]+"${ausnahme_ids[@]}"})
    py_rc=$?
    [ "$py_rc" -eq 0 ] || ungemessen "pip-audit ($name): Auswertung ist gescheitert (rc=$py_rc): $(printf '%s' "$auswertung" | tr '\n' ' ' | cut -c1-300)"
    benutzt="$benutzt$(printf '%s\n' "$auswertung" | sed -n 's/^AUSGENOMMEN \([^ ]*\) .*/\1/p' | tr '\n' ' ')"
    nicht_geprueft=$(printf '%s\n' "$auswertung" | sed -n 's/^UNGEMESSEN //p')
    [ -z "$nicht_geprueft" ] || ungemessen "pip-audit ($name): $(printf '%s' "$nicht_geprueft" | tr '\n' ';')"
    geprueft=$(printf '%s\n' "$auswertung" | sed -n 's/^ANZAHL //p')
    # pip-audit meldet dieselbe Kennung je Alias mehrfach: einmal je Zeile genuegt.
    funde=$(printf '%s\n' "$auswertung" | sed -n 's/^FUND //p' | sort -u)
    if [ -n "$funde" ]; then
        printf 'ROT: Fund in %s:\n' "$name" >&2
        printf '%s\n' "$funde" | sed 's/^/  /' >&2
        fund=1
    elif [ "$pa_rc" -ne 0 ] && { [ "$pa_rc" -ne 1 ] || ! printf '%s\n' "$auswertung" | grep -q '^AUSGENOMMEN '; }; then
        # rc 1 ist bei pip-audit "Fund": ohne Fund im Bericht (auch ausgenommenen) ein Werkzeugfehler.
        ungemessen "pip-audit ($name) endete mit rc=$pa_rc ohne Fund: $(tr '\n' ' ' < "$werkstatt/$name.pa.err" | cut -c1-300)"
    fi
    zahlen+=("$name $geprueft Pakete")
}

zahlen=()
lauf Laufzeit --no-group test
lauf Test --only-group test

for kennung in ${ausnahme_ids[@]+"${ausnahme_ids[@]}"}; do
    case "$benutzt" in
        *" $kennung "*) ;;
        *) echo "Hinweis: Ausnahme $kennung passt zu keinem Fund, sie kann aus .github/pip-audit-ausnahmen.txt gestrichen werden." >&2 ;;
    esac
done
[ "$fund" -eq 0 ] || exit 1
echo "OK: ${zahlen[0]}, ${zahlen[1]} gegen backend/uv.lock geprueft, keine bekannten Luecken (Ausnahmen: ${#ausnahme_ids[@]})."
