#!/bin/sh
# Charakterisierungstests fuer pakete_pruefen.sh (Schwachstellenpruefung der
# Python-Pakete). Das Netz braucht kein Test: uv und pip-audit sind Attrappen auf
# PATH, die Werkzeuge an der Systemgrenze. Die Attrappe von pip-audit liest die
# Exportdatei wirklich (inkl. Plattformmarker, wie das echte Werkzeug) und meldet
# genau die Pakete, die sie sieht. Die echte Nullprobe mit Netz steht im PR.
#
# Leitsatz: "nicht gemessen" ist nie gruen. Jeder Fall, in dem etwas fehlt, muss
# rot sein UND "NICHT GEMESSEN" sagen; ein Fund ist rot ohne diesen Satz.

set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE

hier=$(cd "$(dirname "$0")" && pwd)
skript="$hier/pakete_pruefen.sh"
fehl=0
zahl=0

werkstatt=$(mktemp -d "${TMPDIR:-/tmp}/pakete.XXXXXX") \
    && [ -n "$werkstatt" ] && [ -d "$werkstatt" ] || {
    echo "ABBRUCH: keine Werkstatt anlegbar (mktemp) - die Suite laeuft nicht." >&2
    exit 2
}
trap 'rm -rf "$werkstatt"' EXIT

att="$werkstatt/attrappen"
mkdir -p "$att"

cat > "$att/uv" <<'ATT'
#!/bin/sh
# Attrappe: gibt je nach Gruppe den vorbereiteten Export aus.
[ -n "${FAKE_UV_RC:-}" ] && { echo "uv: kaputt" >&2; exit "$FAKE_UV_RC"; }
case " $* " in
    *" --only-group test "*|*" --no-group test "*) ;;
    *) echo "uv: Gruppe fehlt" >&2; exit 9 ;;
esac
case " $* " in
    *" --only-group test "*) cat "$FAKE_EXPORT_TEST" ;;
    *) cat "$FAKE_EXPORT_LAUFZEIT" ;;
esac
ATT

cat > "$att/pip-audit" <<'ATT'
#!/bin/sh
# Attrappe: liest die Exportdatei (-r), meldet JSON wie pip-audit --format json.
# FAKE_VULN="paket:kennung:fix" laesst genau dieses Paket verwundbar sein,
# ausser die Kennung kommt per --ignore-vuln.
req=; ign=
while [ $# -gt 0 ]; do
    case $1 in
        -r) req=$2; shift ;;
        --ignore-vuln) ign="$ign $2"; shift ;;
    esac
    shift
done
case "${FAKE_PA:-}" in
    kaputt) echo "Traceback: Failed to upgrade pip" >&2; exit 1 ;;
    leer) echo '{"dependencies":[],"fixes":[]}'; exit 0 ;;
esac
awk -v ign=" $ign " -v vuln="${FAKE_VULN:-}" -v modus="${FAKE_PA:-}" '
BEGIN { split(vuln, v, ":"); printf "{\"dependencies\":[" }
/^[A-Za-z0-9_.-]+==/ {
    if ($0 ~ / ; /) next
    if (modus == "weniger" && !weg) { weg = 1; next }
    split($1, p, "==")
    if (n++) printf ","
    erster = (n == 1)
    if (modus == "fremd") p[1] = "fremd" n
    if (erster && modus == "kein_dict") { printf "\"kein-objekt\""; next }
    vs = "\"vulns\":[]"
    if (p[1] == v[1] && index(ign, " " v[2] " ") == 0) {
        vs = "\"vulns\":[{\"id\":\"" v[2] "\",\"fix_versions\":[\"" v[3] "\"],\"aliases\":[" (v[4] != "" ? "\"" v[4] "\"" : "") "],\"description\":\"x\"}]"
        fund = 1
    }
    if (erster && modus == "vulns_null") vs = "\"vulns\":null"
    if (erster && modus == "vulns_string") vs = "\"vulns\":\"abc\""
    if (erster && modus == "vulns_umbenannt") vs = "\"vulnerabilities\":[]"
    if (erster && modus == "skip") vs = "\"skip_reason\":\"kein Wheel\""
    printf "{\"name\":\"%s\",\"version\":\"%s\",%s}", p[1], p[2], vs
}
END { printf "],\"fixes\":[]}\n"; exit (fund ? 1 : (modus == "rc" ? 2 : 0)) }' "$req"
ATT
chmod +x "$att/uv" "$att/pip-audit"

cat > "$werkstatt/lauf.txt" <<'EOT'
aiofiles==24.1.0 \
    --hash=sha256:aa
jinja2==3.1.6 \
    --hash=sha256:bb
colorama==0.4.6 ; sys_platform == 'win32' \
    --hash=sha256:cc
EOT
cat > "$werkstatt/test.txt" <<'EOT'
pytest==9.2.0 \
    --hash=sha256:dd
pluggy==1.6.0 \
    --hash=sha256:ee
EOT
: > "$werkstatt/leer.txt"

# $1 Name  $2 erwarteter rc (0 oder 1)  $3 erwarteter Wortlaut (leer = keiner)
# $4 Wortlaut, der NICHT vorkommen darf (leer = keiner)
# Umgebung des Falls: FAKE_*, AUSNAHMEN (Dateiinhalt, "-" = Datei fehlt), OHNE_LOCK,
# OHNE_UV, OHNE_PA, HEUTE.
lauf() {
    name=$1; erw_rc=$2; wortlaut=$3; verboten=${4:-}
    zahl=$((zahl + 1))
    w="$werkstatt/fall.$zahl"
    mkdir -p "$w/backend" "$w/.github"
    [ -z "${OHNE_LOCK:-}" ] && printf 'version = 1\n' > "$w/backend/uv.lock"
    printf 'name = "x"\n' > "$w/backend/pyproject.toml"
    case "${AUSNAHMEN-}" in
        -) ;;
        *) printf '%s' "${AUSNAHMEN-}" > "$w/.github/pip-audit-ausnahmen.txt" ;;
    esac
    pfad="$werkstatt/pfad.$zahl"
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
    aus=$(PATH="$pfad" PAKETE_WURZEL="$w" PAKETE_HEUTE="${HEUTE:-2026-11-18}" \
          FAKE_EXPORT_LAUFZEIT="${LAUFZEIT:-$werkstatt/lauf.txt}" \
          FAKE_EXPORT_TEST="${TESTEXPORT:-$werkstatt/test.txt}" \
          "$(command -v bash)" "$skript" 2>&1)
    rc=$?
    ok=1
    if [ "$erw_rc" -eq 0 ]; then [ "$rc" -eq 0 ] || ok=0; else [ "$rc" -ne 0 ] || ok=0; fi
    [ -z "$wortlaut" ] || printf '%s' "$aus" | grep -qF -- "$wortlaut" || ok=0
    [ -z "$verboten" ] || ! printf '%s' "$aus" | grep -qF -- "$verboten" || ok=0
    if [ "$ok" -eq 1 ]; then
        echo "gruen $name"
    else
        echo "ROT  $name: erwartet rc=$erw_rc und '$wortlaut', nicht '$verboten' (rc=$rc)" >&2
        printf '%s\n' "$aus" >&2
        fehl=1
    fi
    # Zuweisungen vor einem Funktionsaufruf bleiben in sh bestehen: wegraeumen.
    unset OHNE_LOCK OHNE_UV OHNE_PA FAKE_UV_RC FAKE_PA FAKE_VULN LAUFZEIT TESTEXPORT AUSNAHMEN HEUTE
}

KEINE=""

# Durchstich: sauberer Stand ist gruen und nennt, was geprueft wurde.
AUSNAHMEN="$KEINE" lauf sauberer_stand_ist_gruen 0 "OK" "NICHT GEMESSEN"
# Plattformmarker werden entfernt: colorama (nur Windows) zaehlt mit, 3 + 2 Pakete.
AUSNAHMEN="$KEINE" lauf marker_pakete_werden_mitgeprueft 0 "Laufzeit 3 Pakete" ""
AUSNAHMEN="$KEINE" lauf test_gruppe_wird_getrennt_gezaehlt 0 "Test 2 Pakete" ""

# Nicht gemessen ist nie gruen.
AUSNAHMEN="$KEINE" OHNE_LOCK=1 lauf lock_fehlt_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" OHNE_UV=1 lauf uv_fehlt_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" OHNE_PA=1 lauf pip_audit_fehlt_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" FAKE_UV_RC=3 lauf export_scheitert_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" LAUFZEIT="$werkstatt/leer.txt" lauf leerer_laufzeitexport_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" TESTEXPORT="$werkstatt/leer.txt" lauf leerer_testexport_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=kaputt lauf pip_audit_ohne_ausgabe_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=leer lauf null_geprueft_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=rc lauf pip_audit_rc_ohne_fund_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=kein_dict lauf eintrag_ohne_objekt_bei_rc0_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=vulns_null lauf vulns_null_bei_rc0_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=vulns_string lauf vulns_string_bei_rc0_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=weniger lauf weniger_geprueft_als_gepinnt_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN=- lauf ausnahmedatei_fehlt_ist_rot 1 "NICHT GEMESSEN" "OK"

# Fund: rot, mit Paket, Fassung, Kennung und fixierter Fassung.
AUSNAHMEN="$KEINE" FAKE_VULN="jinja2:PYSEC-0001:3.1.7" lauf fund_laufzeit_ist_rot 1 \
    "jinja2 3.1.6 PYSEC-0001 fix 3.1.7" "NICHT GEMESSEN"
AUSNAHMEN="$KEINE" FAKE_VULN="pytest:PYSEC-0002:9.9" lauf fund_im_test_ist_rot 1 \
    "pytest 9.2.0 PYSEC-0002 fix 9.9" ""

# Ausnahmen: Kennung, Issue, Ablauf. Updates zuerst, Ausnahme ist die Not.
V="jinja2:PYSEC-0001:3.1.7"
AUSNAHMEN="PYSEC-0001 #12 2026-12-31
" FAKE_VULN="$V" lauf gueltige_ausnahme_macht_gruen 0 "OK" ""
AUSNAHMEN="# Kommentar

   PYSEC-0001   12   2026-12-31   
" FAKE_VULN="$V" lauf kommentare_und_leerzeilen_zaehlen_nicht 0 "OK" ""
AUSNAHMEN="PYSEC-0001 #12 2026-11-18
" FAKE_VULN="$V" lauf ablauftag_gilt_noch 0 "OK" ""
AUSNAHMEN="PYSEC-0001 #12 2026-11-17
" FAKE_VULN="$V" lauf abgelaufene_ausnahme_ist_rot 1 "abgelaufen" "OK"
AUSNAHMEN="PYSEC-0001 #12 2026-11-17
" lauf abgelaufene_ausnahme_ohne_fund_ist_rot 1 "abgelaufen" "OK"
AUSNAHMEN="PYSEC-0001 2026-12-31
" FAKE_VULN="$V" lauf ausnahme_ohne_issue_ist_rot 1 "Ausnahme unvollständig" "OK"
AUSNAHMEN="PYSEC-0001 #12
" lauf ausnahme_ohne_datum_ist_rot 1 "Ausnahme unvollständig" "OK"
AUSNAHMEN="PYSEC-0001 #12 2026-12-31 mehr
" lauf ausnahme_mit_zuviel_ist_rot 1 "Ausnahme unvollständig" "OK"
AUSNAHMEN="PYSEC-0001 #12 31.12.2026
" lauf ausnahme_mit_falschem_datum_ist_rot 1 "Datum" "OK"
AUSNAHMEN="PYSEC-0001 #12 2026-13-45
" lauf ausnahme_mit_unmoeglichem_datum_ist_rot 1 "Datum" "OK"
AUSNAHMEN="PYSEC-0001 abc 2026-12-31
" lauf ausnahme_mit_falscher_issue_nummer_ist_rot 1 "Issue" "OK"
AUSNAHMEN="PYSEC-0999 #12 2026-12-31
" FAKE_VULN="$V" lauf fremde_ausnahme_deckt_fund_nicht 1 "PYSEC-0001" "OK"

[ "$fehl" -eq 0 ] && echo "test_pakete_pruefen: alle gruen ($zahl Faelle)"
exit "$fehl"
