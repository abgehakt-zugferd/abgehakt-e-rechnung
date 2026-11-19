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
# FAKE_VULN="paket:kennung:fix[:alias]" laesst genau dieses Paket verwundbar sein.
# Die Attrappe vergleicht den Aufruf EXAKT mit der erwarteten Liste: ein fehlendes
# --require-hashes oder --disable-pip, ein fremdes --ignore-vuln oder ein anderes
# Format macht den Lauf rot (Exit 9, kein JSON). Ausnahmen wertet das Skript selbst aus.
for letztes; do :; done
req=$letztes
[ "$*" = "--require-hashes --disable-pip --format json -r $req" ] || {
    echo "Attrappe: Aufruf weicht ab: $*" >&2
    exit 9
}
ign=
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
    if (modus == "norm") { nn = tolower(p[1]); gsub(/[-_.]+/, "-", nn); p[1] = nn }
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
END { printf "],\"fixes\":[]}\n"; exit (fund ? (modus == "rc2" ? 2 : 1) : (modus == "rc" ? 2 : (modus == "rc1" ? 1 : 0))) }' "$req"
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
cat > "$werkstatt/norm.txt" <<'EOT'
Typing_Extensions==4.12.2 \
    --hash=sha256:ff
zope.interface==7.0 \
    --hash=sha256:gg
EOT
cat > "$werkstatt/test.txt" <<'EOT'
pytest==9.2.0 \
    --hash=sha256:dd
pluggy==1.6.0 \
    --hash=sha256:ee
EOT
: > "$werkstatt/leer.txt"

# $1 Name  $2 erwarteter rc (0 = gruen; 1 = beliebiger Fehler; 2 = genau Exit 2)
# $3 erwarteter Wortlaut (leer = keiner)
# $4 Wortlaut, der NICHT vorkommen darf (leer = keiner)
# Umgebung des Falls: FAKE_*, AUSNAHMEN (Dateiinhalt, "-" = Datei fehlt), OHNE_LOCK,
# OHNE_UV, OHNE_PA, HEUTE.
lauf() {
    name=$1; erw_rc=$2; wortlaut=$3; verboten=${4:-}
    zahl=$((zahl + 1))
    w="$werkstatt/fall.$zahl"
    mkdir -p "$w/backend" "$w/.github"
    [ -z "${OHNE_LOCK:-}" ] && printf 'version = 1\n' > "$w/backend/uv.lock"
    printf '[project]\nname = "x"\n[dependency-groups]\ntest = ["pytest==9.2.0"]\n%s\n' \
        "${PYPROJECT_ZUSATZ-}" > "$w/backend/pyproject.toml"
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
    if [ "$erw_rc" -eq 0 ]; then
        [ "$rc" -eq 0 ] || ok=0
    elif [ "$erw_rc" -eq 2 ]; then
        # A3: ungueltige/zu lange/abgelaufene Ausnahme ergibt genau 2.
        [ "$rc" -eq 2 ] || ok=0
    else
        [ "$rc" -ne 0 ] || ok=0
    fi
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
    unset OHNE_LOCK OHNE_UV OHNE_PA FAKE_UV_RC FAKE_PA FAKE_VULN LAUFZEIT TESTEXPORT AUSNAHMEN HEUTE PYPROJECT_ZUSATZ
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
AUSNAHMEN="$KEINE" FAKE_PA=vulns_umbenannt lauf fehlendes_vulns_nennt_das_paket 1 "aiofiles ohne vulns-Liste" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=skip lauf skip_reason_ist_nicht_geprueft 1 "aiofiles uebersprungen: kein Wheel" "OK"
# Gemeinsame Fassung: Pin-Abgleich nennt Name+Version (fachgleich, anderer Wortlaut).
AUSNAHMEN="$KEINE" FAKE_PA=fremd lauf fremde_namen_gleicher_anzahl_sind_rot 1 "aiofiles" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=fremd lauf fremder_name_im_bericht_wird_genannt 1 "fremd1" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=rc1 lauf pip_audit_rc1_ohne_fund_ist_werkzeugfehler 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=weniger lauf fehlendes_paket_wird_mit_namen_genannt 1 "aiofiles" "OK"
AUSNAHMEN="$KEINE" FAKE_PA=norm LAUFZEIT="$werkstatt/norm.txt" lauf namen_nach_pep503_gleich_ist_gruen 0 "OK" "NICHT GEMESSEN"
AUSNAHMEN="$KEINE" FAKE_PA=weniger lauf weniger_geprueft_als_gepinnt_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN=- lauf ausnahmedatei_fehlt_ist_rot 1 "NICHT GEMESSEN" "OK"

# Gruppen: nur "test" ist zugeordnet; jede andere wuerde in keinem Lauf stehen
# (oder, bei "dev", unbemerkt in der Laufzeit).
AUSNAHMEN="$KEINE" PYPROJECT_ZUSATZ='docs = ["sphinx==7.0"]' lauf unbekannte_gruppe_ist_nicht_gemessen 1 "Gruppe docs" "OK"
AUSNAHMEN="$KEINE" PYPROJECT_ZUSATZ='dev = ["ruff==0.5"]' lauf dev_gruppe_ist_nicht_gemessen 1 "Gruppe dev" "OK"
AUSNAHMEN="$KEINE" PYPROJECT_ZUSATZ='[project.optional-dependencies]
pdf = ["x==1"]' lauf unbekannter_extra_ist_nicht_gemessen 1 "Extra pdf" "OK"
AUSNAHMEN="$KEINE" PYPROJECT_ZUSATZ='[[[kaputt' lauf unlesbare_pyproject_ist_nicht_gemessen 1 "NICHT GEMESSEN" "OK"

# Fund: rot; gemeinsame Fassung meldet LUECKE … behoben in … (fachgleich).
AUSNAHMEN="$KEINE" FAKE_VULN="jinja2:PYSEC-0001:3.1.7" lauf fund_laufzeit_ist_rot 1 \
    "jinja2 3.1.6 PYSEC-0001" "NICHT GEMESSEN"
AUSNAHMEN="$KEINE" FAKE_VULN="pytest:PYSEC-0002:9.9" lauf fund_im_test_ist_rot 1 \
    "pytest 9.2.0 PYSEC-0002" ""

# Ausnahmen: Kennung, Issue, Ablauf, seit. Updates zuerst, Ausnahme ist die Not.
# Heute ist 2026-11-18 (PAKETE_HEUTE). Hoechstfrist 30 Tage, gerechnet ab `seit`.
# A3: ungueltige/zu lange/abgelaufene Ausnahmezeile ergibt Exit 2 (nicht 1).
V="jinja2:PYSEC-0001:3.1.7"
ok_zeile() { AUSNAHMEN="$1
" FAKE_VULN="$V" lauf "$2" 0 "OK" "NICHT GEMESSEN"; }
rot_zeile() { AUSNAHMEN="$1
" FAKE_VULN="$V" lauf "$2" 2 "$3" "OK"; }
ok_zeile "PYSEC-0001 #12 2026-12-10 2026-11-18" gueltige_ausnahme_macht_gruen
AUSNAHMEN="# Kommentar

   PYSEC-0001   12   2026-12-10   2026-11-18   
" FAKE_VULN="$V" lauf kommentare_und_leerzeilen_zaehlen_nicht 0 "OK" ""
ok_zeile "PYSEC-0001 #12 2026-11-18 2026-10-20" ablauftag_gilt_noch
rot_zeile "PYSEC-0001 #12 2026-11-17 2026-10-20" abgelaufene_ausnahme_ist_rot "abgelaufen"
AUSNAHMEN="PYSEC-0001 #12 2026-11-17 2026-10-20
" lauf abgelaufene_ausnahme_ohne_fund_ist_rot 2 "abgelaufen" "OK"
rot_zeile "PYSEC-0001 #12 2026-12-10" ausnahme_ohne_seit_ist_rot "unvollstaendig"
rot_zeile "PYSEC-0001 2026-12-10 2026-11-18" ausnahme_ohne_issue_ist_rot "unvollstaendig"
rot_zeile "PYSEC-0001 #12 2026-12-10 2026-11-18 mehr" ausnahme_mit_zuviel_ist_rot "unvollstaendig"
rot_zeile "PYSEC-0001 #12 31.12.2026 2026-11-18" ausnahme_mit_falschem_datum_ist_rot "Datum"
rot_zeile "PYSEC-0001 #12 2026-13-45 2026-11-18" ausnahme_mit_unmoeglichem_monat_ist_rot "kein Kalendertag"
rot_zeile "PYSEC-0001 #12 2026-02-31 2026-02-01" ablauf_31_februar_ist_kein_kalendertag "2026-02-31 ist kein Kalendertag"
rot_zeile "PYSEC-0001 #12 2026-12-10 2026-02-31" seit_31_februar_ist_kein_kalendertag "2026-02-31 ist kein Kalendertag"
rot_zeile "PYSEC-0001 abc 2026-12-10 2026-11-18" ausnahme_mit_falscher_issue_nummer_ist_rot "Issue"
# Hoechstfrist: ab seit, nicht ab heute; Obergrenze genau 30 Tage.
rot_zeile "PYSEC-0001 #12 2026-12-13 2026-10-29" frist_zaehlt_ab_seit_nicht_ab_heute "laenger als 30 Tage ab seit"
ok_zeile "PYSEC-0001 #12 2026-11-19 2026-10-20" frist_30_tage_ab_seit_ist_gruen
rot_zeile "PYSEC-0001 #12 2026-11-20 2026-10-20" frist_31_tage_ab_seit_ist_rot "laenger als 30 Tage ab seit"
rot_zeile "PYSEC-0001 #12 9999-12-31 2026-11-18" unbefristete_ausnahme_ist_rot "laenger als 30 Tage ab seit"
rot_zeile "PYSEC-0001 #12 2026-11-25 2026-11-19" seit_in_der_zukunft_ist_rot "seit liegt in der Zukunft"
rot_zeile "PYSEC-0001 #12 2026-11-05 2026-11-10" ablauf_vor_seit_ist_rot "Ablauf liegt vor seit"
AUSNAHMEN="PYSEC-0999 #12 2026-12-10 2026-11-18
" FAKE_VULN="$V" lauf fremde_ausnahme_deckt_fund_nicht 1 "PYSEC-0001" "OK"
AUSNAHMEN="PYSEC-0001 #12 2026-12-10 2026-11-18
" FAKE_PA=rc2 FAKE_VULN="$V" lauf rc2_trotz_ausgenommenem_fund_ist_rot 1 "NICHT GEMESSEN" "OK"
AUSNAHMEN="CVE-2026-0001 #12 2026-12-10 2026-11-18
" FAKE_VULN="jinja2:PYSEC-0001:3.1.7:CVE-2026-0001" lauf ausnahme_ueber_alias_macht_gruen 0 "OK" "NICHT GEMESSEN"
# Hinweis, nicht rot: gemeinsame Fassung sagt "keiner Luecke" statt "keinem Fund".
AUSNAHMEN="PYSEC-0999 #12 2026-12-10 2026-11-18
" lauf ungenutzte_ausnahme_wird_als_hinweis_genannt 0 "Hinweis: Ausnahme PYSEC-0999 passt zu keiner Luecke" "NICHT GEMESSEN"
AUSNAHMEN="PYSEC-0001 #12 2026-12-10 2026-11-18
" FAKE_VULN="$V" lauf genutzte_ausnahme_ist_kein_hinweis 0 "OK" "Hinweis"
AUSNAHMEN="PYSEC-0002 #12 2026-12-10 2026-11-18
" FAKE_VULN="pytest:PYSEC-0002:9.9" lauf ausnahme_deckt_fund_im_test_lauf_ist_kein_hinweis 0 "OK" "Hinweis"

# Architektur-Lint (der Text ist hier die Regel): jede Workflow-Datei, die das Skript
# oder der Workflow beim Namen nennt, muss es geben. Zeilen mit # zaehlen mit, denn
# gerade die Kopfkommentare lagen daneben.
wurzel=$(cd "$hier/.." && pwd)
zahl=$((zahl + 1))
genannt=$(grep -ho '\.github/workflows/[A-Za-z0-9_.-]*\.yml' "$skript" \
    "$wurzel/.github/pip-audit-ausnahmen.txt" | sort -u)
if [ -z "$genannt" ]; then
    echo "ROT  genannte_workflows_existieren: kein Workflow genannt, die Pruefung misst nichts" >&2
    fehl=1
else
    fehlt=
    for f in $genannt; do [ -f "$wurzel/$f" ] || fehlt="$fehlt $f"; done
    if [ -n "$fehlt" ]; then
        echo "ROT  genannte_workflows_existieren: nicht vorhanden:$fehlt" >&2
        fehl=1
    else
        echo "gruen genannte_workflows_existieren"
    fi
fi

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
        return
    fi
    if [ "$v_wf" = "$v_df" ]; then
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

wf_kopie="$werkstatt/paketpruefung.yml"
df_kopie="$werkstatt/Dockerfile.uv"
cp "$wurzel/.github/workflows/paketpruefung.yml" "$wf_kopie"
cp "$wurzel/backend/Dockerfile" "$df_kopie"
# Abweichende Workflow-Version; Dockerfile unveraendert (Kopie).
awk '{gsub(/uv==0\.11\.32/, "uv==0.0.1")}1' "$wf_kopie" > "$wf_kopie.tmp" \
    && mv "$wf_kopie.tmp" "$wf_kopie"
pruefe_uv_versionen uv_version_weicht_ab_ist_rot "$wf_kopie" "$df_kopie" abweichend

: > "$werkstatt/uv-leer.yml"
pruefe_uv_versionen uv_version_fehlt_ist_nicht_gemessen \
    "$werkstatt/uv-leer.yml" "$df_kopie" ungemessen

pruefe_uv_versionen uv_version_workflow_und_dockerfile_gleich \
    "$wurzel/.github/workflows/paketpruefung.yml" \
    "$wurzel/backend/Dockerfile" gruen

[ "$fehl" -eq 0 ] && echo "test_pakete_pruefen: alle gruen ($zahl Faelle)"
exit "$fehl"
