#!/bin/sh
# Gemeinsame Hilfen fuer test_pakete_pruefen.sh.

schreib_auswerter_attrappe() {
    # $1 Name  $2 Exitcode  $3 stdout-literal  $4 stderr-literal
    ziel="$werkstatt/auswerter.$1.py"
    cat > "$ziel" <<ATT
#!/usr/bin/env python3
import sys

modus = sys.argv[1] if len(sys.argv) > 1 else ""
if modus == "vorbereiten":
    with open(sys.argv[2], "r", encoding="utf-8") as f:
        sys.stdout.write(f.read())
    sys.exit(0)
if modus == "auswerten":
    sys.stdout.write($3)
    sys.stderr.write($4)
    sys.exit($2)
sys.exit(9)
ATT
    chmod +x "$ziel"
    printf '%s\n' "$ziel"
}

tp_baue_fallwurzel() {
    # $1 Zielverzeichnis
    ziel=$1
    mkdir -p "$ziel/backend" "$ziel/.github"
    [ -z "${OHNE_LOCK:-}" ] && printf 'version = 1\n' > "$ziel/backend/uv.lock"
    printf '[project]\nname = "x"\n[dependency-groups]\ntest = ["pytest==9.2.0"]\n%s\n' \
        "${PYPROJECT_ZUSATZ-}" > "$ziel/backend/pyproject.toml"
    case "${AUSNAHMEN-}" in
        -) ;;
        *) printf '%s' "${AUSNAHMEN-}" > "$ziel/.github/pip-audit-ausnahmen.txt" ;;
    esac
}

tp_baue_toolpfad() {
    # $1 Zielpfad
    pfad=$1
    mkdir -p "$pfad"
    for b in sh awk grep sed date cat tr wc head sort mktemp rm mkdir cut printf dirname; do
        for d in /usr/bin /bin; do
            [ -x "$d/$b" ] && { ln -sf "$d/$b" "$pfad/$b"; break; }
        done
    done
    ln -sf "$(command -v python3)" "$pfad/python3"
    ln -sf "$(command -v bash)" "$pfad/bash"
    [ -z "${OHNE_UV:-}" ] && ln -sf "$att/uv" "$pfad/uv"
    [ -z "${OHNE_PA:-}" ] && ln -sf "$att/pip-audit" "$pfad/pip-audit"
}

tp_ist_erwartet() {
    # $1 rc  $2 erwarteter-rc-code(0=gruen,1=fehler,2=genau2) $3 ausgabe
    # $4 muss-enthalten $5 darf-nicht
    rc=$1
    erw=$2
    aus=$3
    muss=$4
    darf_nicht=$5
    if [ "$erw" -eq 0 ]; then
        [ "$rc" -eq 0 ] || return 1
    elif [ "$erw" -eq 2 ]; then
        # A3: ungueltige/zu lange/abgelaufene Ausnahme ergibt genau 2.
        [ "$rc" -eq 2 ] || return 1
    else
        [ "$rc" -ne 0 ] || return 1
    fi
    [ -z "$muss" ] || printf '%s' "$aus" | grep -qF -- "$muss" || return 1
    [ -z "$darf_nicht" ] || ! printf '%s' "$aus" | grep -qF -- "$darf_nicht" || return 1
    return 0
}

# $1 Name  $2 erwarteter rc (0 = gruen; 1 = beliebiger Fehler; 2 = genau Exit 2)
# $3 erwarteter Wortlaut in zusammengefuehrter Ausgabe (leer = keiner)
# $4 Wortlaut, der NICHT vorkommen darf (leer = keiner)
# $5 optional: Wortlaut, der auf stderr stehen muss
# $6 optional: Wortlaut, der auf stdout NICHT stehen darf
# Umgebung des Falls: FAKE_*, AUSNAHMEN (Dateiinhalt, "-" = Datei fehlt), OHNE_LOCK,
# OHNE_UV, OHNE_PA, HEUTE, AUSWERTER (Test-Naht fuer den Auswerter-Pfad).
# PAKETE_AUSWERTER wird immer gesetzt (auch leer): so bleibt leer vs. ungesetzt
# unterscheidbar; ${AUSWERTER:-} allein wuerde beides zur leeren Übergabe.
lauf() {
    name=$1
    erw_rc=$2
    wortlaut=$3
    verboten=${4:-}
    muss_stderr=${5:-}
    nicht_stdout=${6:-}
    zahl=$((zahl + 1))
    w="$werkstatt/fall.$zahl"
    tp_baue_fallwurzel "$w"
    pfad="$werkstatt/pfad.$zahl"
    tp_baue_toolpfad "$pfad"
    out_f="$w/stdout.txt"
    err_f="$w/stderr.txt"
    PATH="$pfad" PAKETE_WURZEL="$w" PAKETE_HEUTE="${HEUTE:-2026-11-18}" \
        PAKETE_AUSWERTER="${AUSWERTER:-}" \
        FAKE_EXPORT_LAUFZEIT="${LAUFZEIT:-$werkstatt/lauf.txt}" \
        FAKE_EXPORT_TEST="${TESTEXPORT:-$werkstatt/test.txt}" \
        "$(command -v bash)" "$skript" >"$out_f" 2>"$err_f"
    rc=$?
    aus=$(cat "$out_f"; cat "$err_f")
    if tp_ist_erwartet "$rc" "$erw_rc" "$aus" "$wortlaut" "$verboten" \
        && tp_strom_ok "$out_f" "$err_f" "$muss_stderr" "$nicht_stdout"; then
        echo "gruen $name"
    else
        echo "ROT  $name: erwartet rc=$erw_rc und '$wortlaut', nicht '$verboten' (rc=$rc)" >&2
        printf '%s\n' "$aus" >&2
        fehl=1
    fi
    # Zuweisungen vor einem Funktionsaufruf bleiben in sh bestehen: wegraeumen.
    unset OHNE_LOCK OHNE_UV OHNE_PA FAKE_UV_RC FAKE_PA FAKE_VULN LAUFZEIT TESTEXPORT
    unset AUSNAHMEN HEUTE PYPROJECT_ZUSATZ AUSWERTER
}

# $1 stdout-Datei  $2 stderr-Datei  $3 muss-auf-stderr  $4 darf-nicht-auf-stdout
tp_strom_ok() {
    out_f=$1
    err_f=$2
    muss_stderr=$3
    nicht_stdout=$4
    if [ -n "$muss_stderr" ]; then
        grep -qF -- "$muss_stderr" "$err_f" || return 1
    fi
    if [ -n "$nicht_stdout" ]; then
        ! grep -qF -- "$nicht_stdout" "$out_f" || return 1
    fi
    return 0
}

# uv-Version: paketpruefung.yml (pip install uv==…) und backend/Dockerfile
# (ghcr.io/astral-sh/uv:…) muessen dieselbe Fassung pinnen; sonst misst die
# Paketpruefung mit einem anderen Exporter als der Abbild-Bau. Fehlt eine Angabe
# oder ist sie nicht lesbar: NICHT GEMESSEN, nicht gruen.
# $1 workflow-Pfad  $2 Dockerfile-Pfad → gruen|abweichend|ungemessen
uv_version_lage() {
    wf=$1
    df=$2
    [ -f "$wf" ] && [ -r "$wf" ] || { echo ungemessen; return; }
    [ -f "$df" ] && [ -r "$df" ] || { echo ungemessen; return; }
    # workflow: "uv==0.11.32" (pip install); Dockerfile: "ghcr.io/astral-sh/uv:0.11.32@"
    v_wf=$(grep -oE 'uv==[0-9]+\.[0-9]+\.[0-9]+' "$wf" | head -n 1 | sed 's/^uv==//')
    v_df=$(grep -oE 'ghcr\.io/astral-sh/uv:[0-9]+\.[0-9]+\.[0-9]+' "$df" \
        | head -n 1 | sed 's/^.*://')
    if [ -z "$v_wf" ] || [ -z "$v_df" ]; then
        echo ungemessen
    elif [ "$v_wf" = "$v_df" ]; then
        echo gruen
    else
        echo abweichend
    fi
}

# $1 Name  $2 workflow  $3 Dockerfile  $4 erwartet (gruen|abweichend|ungemessen)
pruefe_uv_versionen() {
    name=$1
    zahl=$((zahl + 1))
    ist=$(uv_version_lage "$2" "$3")
    if [ "$ist" = "$4" ]; then
        echo "gruen $name"
    else
        echo "ROT  $name: erwartet $4, war $ist" >&2
        fehl=1
    fi
}
