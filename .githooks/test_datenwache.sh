#!/bin/sh
# Charakterisierungstests fuer datenwache.sh (Issue #49).
# Das echte Skript laeuft gegen Wegwerf-Repos; ZEMP_ECHTDATEN_MUSTER wird in jedem
# Fall explizit gesetzt, damit kein Test an ~/.zemp/ haengt.

set -u

hier=$(cd "$(dirname "$0")" && pwd)
wache="$hier/datenwache.sh"
leer=0000000000000000000000000000000000000000
fehl=0
werkstatt=$(mktemp -d)
trap 'rm -rf "$werkstatt"' EXIT

neues_repo() {
    d=$(mktemp -d "$werkstatt/repo.XXXXXX")
    git -C "$d" init -q
    git -C "$d" config user.name probe
    git -C "$d" config user.email probe@example.invalid
    printf '%s\n' "$d"
}

commit_mit() {
    printf '%s\n' "$3" > "$1/$2"
    git -C "$1" add -f "$2"
    git -C "$1" commit -qm "probe" >/dev/null
    git -C "$1" rev-parse HEAD
}

lauf() {
    aus=$( cd "$1" && printf 'refs/heads/probe %s refs/heads/probe %s\n' "$2" "$3" \
        | ZEMP_ECHTDATEN_MUSTER="$4" "$wache" 2>&1 )
    rc=$?
}

befund() {
    if [ "$rc" -ne "$2" ]; then
        echo "ROT  $1: rc=$rc, erwartet $2" >&2; echo "$aus" >&2; fehl=1; return
    fi
    if [ -n "$3" ] && ! printf '%s' "$aus" | grep -qF -- "$3"; then
        echo "ROT  $1: Ausgabe ohne '$3'" >&2; echo "$aus" >&2; fehl=1; return
    fi
    echo "gruen $1"
}

# Muster ohne IBAN-artige Literale in dieser Datei (sonst blockiert die Wache den Push).
_iban_probe() {
    _p1="DE"; _p2="12"; _p3="3456 7890 1234 5678 90"
    printf 'probe %s%s %s\n' "$_p1" "$_p2" "$_p3"
}

_ust_probe() {
    # Echt aussehend (nicht konstruiert): bleibt geblockt.
    _p1="DE"; _p2="815739204"
    printf 'probe %s%s ende\n' "$_p1" "$_p2"
}

_ust_fixture() {
    # Hausfixture: aufsteigend mit Umbruch erlaubt (Issue #88).
    _p1="DE"; _p2="123456789"
    printf 'vat_id="%s%s"\n' "$_p1" "$_p2"
}

_ust_fixture_absteigend() {
    _p1="DE"; _p2="987654321"
    printf 'vat_id="%s%s"\n' "$_p1" "$_p2"
}

_ust_fixture_gleich() {
    # Gleiche Ziffer = Schritt 0; ohne diesen Zweig faellt die Erkennung durch.
    _p1="DE"; _p2="111111111"
    printf 'vat_id="%s%s"\n' "$_p1" "$_p2"
}

_ust_ein_fehler() {
    # Fast aufsteigend, ein Fehler am Ende: bleibt geblockt.
    _p1="DE"; _p2="123456780"
    printf 'probe %s%s ende\n' "$_p1" "$_p2"
}

_key_probe() {
    _a="-----BEGIN "; _b="OPENSSH PRIVATE KEY-----"
    printf '%s%s\n' "$_a" "$_b"
}

_steuer_probe() {
    # Echt aussehend (nicht konstruiert): bleibt geblockt.
    printf 'probe %s/%s/%s ende\n' "21" "815" "00042"
}

_steuer_fixture_zehn() {
    printf 'tax_number="%s/%s/%s"\n' "12" "345" "67890"
}

_steuer_fixture_elf() {
    printf 'tax_number="%s/%s/%s"\n' "123" "456" "78901"
}

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_iban_probe)")
lauf "$r" "$s" "$leer" /nicht/da
befund "iban_wird_erkannt" 1 "IBAN-Format"

r=$(neues_repo); s=$(commit_mit "$r" a.txt "harmloser Text, Betrag 24,30 Euro, 2026-08-23")
lauf "$r" "$s" "$leer" /nicht/da
befund "sauberer_commit_laeuft_durch" 0 ""

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_iban_probe)")
aus=$( cd "$r" && printf 'refs/heads/probe %s refs/heads/probe %s\n' "$s" "$leer" \
    | DATENWACHE_UEBERSTIMMT=1 ZEMP_ECHTDATEN_MUSTER=/nicht/da "$wache" 2>&1 ); rc=$?
befund "ueberstimmen_laeuft_durch" 0 "UEBERSTIMMT"

r=$(neues_repo); s=$(commit_mit "$r" .env "GEHEIM=probe")
lauf "$r" "$s" "$leer" /nicht/da
befund "env_datei_wird_erkannt" 1 ".env-Datei"

r=$(neues_repo); s=$(commit_mit "$r" .env.example "GEHEIM=hier-eintragen")
lauf "$r" "$s" "$leer" /nicht/da
befund "env_example_ist_erlaubt" 0 ""

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_ust_probe)")
lauf "$r" "$s" "$leer" /nicht/da
befund "ust_idnr_wird_erkannt" 1 "USt-IdNr-Format"

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_steuer_probe)")
lauf "$r" "$s" "$leer" /nicht/da
befund "steuernummer_wird_erkannt" 1 "Steuernummer-Format"

# Issue #88: konstruierte Fixture-Folgen (Umbruch 9->0) durchlassen.
r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_ust_fixture)")
lauf "$r" "$s" "$leer" /nicht/da
befund "ust_fixture_aufsteigend_laeuft_durch" 0 ""

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_ust_fixture_absteigend)")
lauf "$r" "$s" "$leer" /nicht/da
befund "ust_fixture_absteigend_laeuft_durch" 0 ""

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_ust_fixture_gleich)")
lauf "$r" "$s" "$leer" /nicht/da
befund "ust_fixture_gleich_laeuft_durch" 0 ""

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_steuer_fixture_zehn)")
lauf "$r" "$s" "$leer" /nicht/da
befund "steuer_fixture_zehn_laeuft_durch" 0 ""

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_steuer_fixture_elf)")
lauf "$r" "$s" "$leer" /nicht/da
befund "steuer_fixture_elf_laeuft_durch" 0 ""

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_ust_ein_fehler)")
lauf "$r" "$s" "$leer" /nicht/da
befund "ust_ein_fehler_bleibt_geblockt" 1 "USt-IdNr-Format"

r=$(neues_repo); s=$(commit_mit "$r" a.txt "$(_key_probe)")
lauf "$r" "$s" "$leer" /nicht/da
befund "privater_schluessel_wird_erkannt" 1 "privater Schluessel"

m="$werkstatt/muster.txt"
printf '# Kommentar\nProbe-Autorin\n' > "$m"
r=$(neues_repo); s=$(commit_mit "$r" a.txt "Probe-Autorin bekommt 25 Prozent")
lauf "$r" "$s" "$leer" "$m"
befund "zusatzmuster_greifen" 1 "Zusatzmuster"

r=$(neues_repo); commit_mit "$r" a.txt "harmlos" >/dev/null
lauf "$r" "$leer" "$leer" /nicht/da
befund "zweigloeschung_wird_ignoriert" 0 ""

r=$(neues_repo)
alt=$(commit_mit "$r" alt.txt "$(_iban_probe)")
neu=$(commit_mit "$r" neu.txt "harmloser Nachtrag")
lauf "$r" "$neu" "$alt" /nicht/da
befund "nur_neue_commits_zaehlen" 0 ""

if [ "$fehl" -ne 0 ]; then
    echo "" >&2
    echo "test_datenwache: ROT" >&2
    exit 1
fi
echo "test_datenwache: alle gruen"
exit 0
