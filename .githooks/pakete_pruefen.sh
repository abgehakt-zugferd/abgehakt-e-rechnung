#!/usr/bin/env bash
# Schwachstellenpruefung der Python-Pakete gegen backend/uv.lock.
#
# Aufrufer ist .github/workflows/paketpruefung.yml; das Skript liegt hier, damit es
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
# Plattformmarker (`; sys_platform == 'win32'`) entfernt `vorbereiten` im gemeinsamen
# Auswerter (`.githooks/pip-audit-auswerter/`), damit pip-audit Pakete aller
# Plattformen prueft.
#
# "Nicht gemessen" ist nie gruen. Fehlt uv.lock, uv, pip-audit, python3, die
# Ausnahmendatei oder die Ausgabe, oder sind es null Pakete, oder weniger geprueft als
# gepinnt: Exit ungleich 0 mit "NICHT GEMESSEN" und dem Grund. Ein Fund ist Exit 1.
# Ungueltige/abgelaufene Ausnahme: Exit 2 (gemeinsamer Auswerter).
#
# Ausnahmen (.github/pip-audit-ausnahmen.txt): Format und Regeln stehen im Kopf dieser
# Datei und im gemeinsamen Auswerter (echter Kalendertag, hoechstens 30 Tage ab `seit`,
# Ablauf). Der Auswerter filtert selbst, nicht per --ignore-vuln.
#
# Gruppen: nur "test" ist zugeordnet. Jede weitere Gruppe oder jeder Extra in
# pyproject.toml ergibt NICHT GEMESSEN mit Namen (App-Sache, nicht im Auswerter).
#
# Umgebung (fuer Tests): PAKETE_WURZEL (Repo-Wurzel), PAKETE_HEUTE (JJJJ-MM-TT).
set -uo pipefail
set -f

wurzel="${PAKETE_WURZEL:-$(cd "$(dirname "$0")/.." && pwd)}"
heute="${PAKETE_HEUTE:-$(date +%Y-%m-%d)}"
lock="$wurzel/backend/uv.lock"
ausnahmen="$wurzel/.github/pip-audit-ausnahmen.txt"
# Gemeinsamer Auswerter (Kopie). Ohne -I: Nachbarmodule _ausnahmen/_bericht.
auswerter="${PAKETE_AUSWERTER:-$(cd "$(dirname "$0")" && pwd)/pip-audit-auswerter/pip_audit_auswerten.py}"

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
[ -f "$auswerter" ] || ungemessen "Auswerter fehlt: $auswerter"

# Exit des Auswerters gegen die ERGEBNIS-Schlusszeile. Passen sie nicht, gilt
# der Lauf als nicht gemessen (Vertrag der gemeinsamen Fassung).
ergebnis_passt() {
    rc=$1
    ausgabe=$2
    letzte=$(printf '%s\n' "$ausgabe" | awk 'NF{line=$0} END{print line}')
    case "$rc" in
        0) printf '%s' "$letzte" | grep -q '^ERGEBNIS SAUBER (' ;;
        1) printf '%s' "$letzte" | grep -q '^ERGEBNIS LUECKE (' ;;
        2) printf '%s' "$letzte" | grep -q '^ERGEBNIS NICHT GEMESSEN' ;;
        *) return 1 ;;
    esac
}

# --- ein Lauf: Export, vorbereiten, pip-audit, auswerten --------------------------
# $1 Name  $2.. Gruppenschalter fuer uv export.
fund=0
nicht_gemessen=0
# HINWEIS je Lauf waere falsch: Ausnahme nur in Laufzeit trifft im Test-Lauf
# als ungenutzt. Wie bisher ueber beide Laeufe sammeln (App-Sache).
benutzt=" "
: > "$werkstatt/hinweise.txt"
lauf() {
    name=$1; shift
    exp_roh="$werkstatt/$name.roh"
    exp="$werkstatt/$name.txt"
    if ! ( cd "$wurzel/backend" && uv export --frozen --format requirements-txt \
            --no-emit-project --no-header --no-annotate "$@" ) > "$exp_roh" 2> "$werkstatt/$name.uv.err"; then
        ungemessen "uv export ($name) ist gescheitert: $(tr '\n' ' ' < "$werkstatt/$name.uv.err")"
    fi
    if ! python3 "$auswerter" vorbereiten "$exp_roh" > "$exp" 2> "$werkstatt/$name.vor.err"; then
        ungemessen "vorbereiten ($name): $(tr '\n' ' ' < "$werkstatt/$name.vor.err" | cut -c1-300)"
    fi
    gepinnt=$(grep -cE '^[A-Za-z0-9_.-]+==' "$exp" || true)
    [ "$gepinnt" -gt 0 ] || ungemessen "Export ($name) enthaelt kein einziges gepinntes Paket."

    pip-audit --require-hashes --disable-pip --format json \
        -r "$exp" \
        > "$werkstatt/$name.json" 2> "$werkstatt/$name.pa.err"
    pa_rc=$?
    auswertung=$(python3 "$auswerter" auswerten \
        --pins "$exp" \
        --bericht "$werkstatt/$name.json" \
        --rc "$pa_rc" \
        --ausnahmen "$ausnahmen" \
        --heute "$heute" 2> "$werkstatt/$name.aus.err")
    py_rc=$?
    auswertung_err=$(tr '\n' ' ' < "$werkstatt/$name.aus.err" | cut -c1-300)
    if ! ergebnis_passt "$py_rc" "$auswertung"; then
        ungemessen "pip-audit ($name): Exit $py_rc und ERGEBNIS passen nicht: $(printf '%s %s' "$auswertung" "$auswertung_err" | tr '\n' ' ' | cut -c1-300)"
    fi
    # NICHT GEMESSEN / LUECKE sofort; HINWEIS erst nach beiden Laeufen.
    printf '%s\n' "$auswertung" | grep -E '^(NICHT GEMESSEN|LUECKE) ' \
        | sed 's/^NICHT GEMESSEN /ROT: NICHT GEMESSEN: /; s/^LUECKE /ROT: Fund in '"$name"': /' >&2 || true
    benutzt="$benutzt$(printf '%s\n' "$auswertung" | sed -n 's/^AUSGENOMMEN \([^ ]*\) .*/\1/p' | tr '\n' ' ')"
    printf '%s\n' "$auswertung" | sed -n 's/^HINWEIS Ausnahme \([^ ]*\) .*/\1/p' \
        >> "$werkstatt/hinweise.txt" || true
    if [ "$py_rc" -eq 2 ]; then
        nicht_gemessen=1
    elif [ "$py_rc" -eq 1 ]; then
        fund=1
    elif [ "$py_rc" -ne 0 ]; then
        ungemessen "pip-audit ($name): unerwarteter Auswerter-rc=$py_rc"
    fi
    # Kein tail: Test-PATH hat es nicht. Letzte ERGEBNIS-Zeile zaehlt.
    geprueft=
    while IFS= read -r zeile || [ -n "$zeile" ]; do
        case "$zeile" in
            ERGEBNIS\ *\(*\ Pakete\))
                geprueft=${zeile##*(}
                geprueft=${geprueft%% Pakete*}
                ;;
        esac
    done <<EOF
$auswertung
EOF
    [ -n "$geprueft" ] || geprueft=0
    zahlen+=("$name $geprueft Pakete")
}

# Gruppen: nur "test" ist zugeordnet (App-Sache).
gruppen_aus=$(python3 - "$wurzel/backend/pyproject.toml" <<'PY'
import sys, tomllib
bekannte = {"test"}
daten = tomllib.load(open(sys.argv[1], "rb"))
for name in sorted(set(daten.get("dependency-groups", {})) - bekannte):
    print("UNBEKANNT Gruppe", name)
for name in sorted(daten.get("project", {}).get("optional-dependencies", {})):
    print("UNBEKANNT Extra", name)
PY
)
gruppen_rc=$?
[ "$gruppen_rc" -eq 0 ] || ungemessen "backend/pyproject.toml nicht auswertbar (rc=$gruppen_rc): $(printf '%s' "$gruppen_aus" | tr '\n' ' ' | cut -c1-200)"
[ -z "$gruppen_aus" ] || ungemessen "$(printf '%s' "$gruppen_aus" | sed 's/^UNBEKANNT //' | tr '\n' ',') in backend/pyproject.toml keinem Lauf zugeordnet (bekannt: nur Gruppe test); in pakete_pruefen.sh zuordnen."

zahlen=()
lauf Laufzeit --no-group test
lauf Test --only-group test

# Ungenutzte Ausnahmen erst jetzt: Treffer in einem Lauf deckt den Hinweis.
if [ -s "$werkstatt/hinweise.txt" ]; then
    sort -u "$werkstatt/hinweise.txt" | while IFS= read -r kennung || [ -n "$kennung" ]; do
        [ -n "$kennung" ] || continue
        case "$benutzt" in
            *" $kennung "*) ;;
            *) echo "Hinweis: Ausnahme $kennung passt zu keiner Luecke" >&2 ;;
        esac
    done
fi

[ "$nicht_gemessen" -eq 0 ] || exit 2
[ "$fund" -eq 0 ] || exit 1
echo "OK: ${zahlen[0]}, ${zahlen[1]} gegen backend/uv.lock geprueft, keine bekannten Luecken."
