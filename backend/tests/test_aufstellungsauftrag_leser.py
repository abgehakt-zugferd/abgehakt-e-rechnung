"""Der Leser fuer aufstellungsauftrag (§ 8b, Fassung 1.7).

Reihenfolge der Regeln wie im Leser: Feldbestand, dann Werte und Summen,
DANN die Dateien - nur ein in sich brauchbarer Beleg wird gegen die Dateien
gehalten. Die Aufstellung ist keine Rechnung (§ 14 UStG): kein typcode, keine
Steuerfelder; die Quellensteuer ist ein Einbehalt des Auszahlers. Jeder Fall
hier ist erfunden (helpers/uebergabe.aufstellungsauftrag), die Anlagen sind
Bytes ueber die Empfangslage, keine Dateien.
"""

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
from tests.helpers.uebergabe import (
    ANLAGE_ABRECHNUNGSBERICHT,
    ANLAGE_ZAHLUNGSBERICHT,
    PARTNER_A,
    anlage,
    aufstellungsauftrag,
    auftrag,
    beleg,
    probe_anlagen,
    rechnungsauftrag,
    schluesselpaar,
)

SCHLUESSEL_IM_BELEG = "plattform:2026-02:kanal-b:x1"


class _Lage(Empfangslage):
    """Eine Lage mit Bestand: je Auftragsschluessel der Beleg, der dazu
    bereits besteht, die bekannten Partner und die abgelegten Anlagen.

    Ohne anlagen gilt jede Anlage als fehlend - die leere Lage ist hier die
    ehrliche Voreinstellung, denn § 8b haelt jeden Beleg gegen die Dateien.
    """

    def __init__(self, dokumente=None, partner=(), anlagen=None):
        self._dokumente = dokumente or {}
        self._partner = partner
        self._anlagen = anlagen if anlagen is not None else {}

    def dokument_zu_auftragsschluessel(self, schluessel):
        return self._dokumente.get(schluessel)

    def partner_bekannt(self, partner_id):
        return partner_id in self._partner

    def anlagen_bytes(self, sha256):
        return self._anlagen.get(sha256)


@pytest.fixture
def schluessel(tmp_path):
    return schluesselpaar(tmp_path)


def _urteil(schluessel, nutzlast, lage=None, **umschlag_aenderungen):
    umschlag_aenderungen.setdefault("nutzlast_art", "aufstellungsauftrag")
    roh = beleg(schluessel[0], nutzlast, **umschlag_aenderungen)
    if lage is None:
        lage = _Lage(partner=(PARTNER_A,), anlagen=probe_anlagen())
    return beleg_beurteilen(roh, lage, schluessel_wurzel=schluessel[1])


def _befunde(urteil) -> list:
    return [(f.code, f.pfad) for f in urteil.feststellungen]


# ---- Regel 1 und 2: die Art ist lesbar, der Feldbestand ----


def test_ein_gueltiger_aufstellungsauftrag_wird_angenommen(schluessel):
    """Regel 1: Die Art steht in LESBARE_ARTEN - vorher fiel jeder gueltig
    signierte aufstellungsauftrag an der Artprobe. netto x kurs ergibt
    zahlbetrag hier nicht, und gerade das ist angenommen."""
    urteil = _urteil(schluessel, aufstellungsauftrag())

    assert urteil.angenommen, _befunde(urteil)
    assert urteil.feststellungen == ()
    assert urteil.nutzlast_art == "aufstellungsauftrag"


def test_ein_typcode_ist_ein_unbekanntes_feld(schluessel):
    """Regel 2: Die Aufstellung ist keine Rechnung (§ 14 UStG) - auch ein
    richtiger typcode waere ein Feld zu viel."""
    urteil = _urteil(schluessel, aufstellungsauftrag(typcode="380"))

    assert _befunde(urteil) == [("UNBEKANNTES_FELD", "$.nutzlast.typcode")]


def test_steuerfelder_gibt_es_nicht(schluessel):
    """Regel 2: Keine Steuer an der Aufstellung. Die Steuer entsteht hier
    nicht, und die Quellensteuer ist ein Einbehalt des Auszahlers - auch
    0.00 liessen zwei Stellen dieselbe Zahl behaupten."""
    nutzlast = aufstellungsauftrag()
    nutzlast["betraege"]["steuer"] = "0.00"

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("UNBEKANNTES_FELD", "$.nutzlast.betraege.steuer")]


def test_ein_fehlendes_pflichtfeld_ist_kein_unbekanntes_feld(schluessel):
    """Regel 2: zahlung ist bekannt und nicht da - PFLICHTFELD_FEHLT."""
    nutzlast = aufstellungsauftrag()
    del nutzlast["zahlung"]

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("PFLICHTFELD_FEHLT", "$.nutzlast.zahlung")]


def test_anlagen_bleiben_den_beiden_anderen_arten_fremd(schluessel):
    """Regel 8: anlagen traegt in 1.7 nur der aufstellungsauftrag - im
    abrechnungsauftrag und im rechnungsauftrag bleibt das Feld unbekannt,
    auch gefuellt."""
    anlagen = [anlage("abrechnungsbericht", "bericht.xlsx", ANLAGE_ABRECHNUNGSBERICHT)]

    abrechnung = _urteil(
        schluessel, auftrag(anlagen=anlagen), nutzlast_art="abrechnungsauftrag",
    )
    rechnung = _urteil(
        schluessel, rechnungsauftrag(anlagen=anlagen), nutzlast_art="rechnungsauftrag",
    )

    assert _befunde(abrechnung) == [("UNBEKANNTES_FELD", "$.nutzlast.anlagen")]
    assert _befunde(rechnung) == [("UNBEKANNTES_FELD", "$.nutzlast.anlagen")]


# ---- Regel 2: auftragsschluessel, kunde, leistungszeitraum (gemeinsam mit 8a) ----


@pytest.mark.parametrize("wert", [
    "Plattform:2026-02",     # Grossbuchstabe ist eine andere Form
    "plattform 2026",        # Leerzeichen
    "plattform_2026",        # Unterstrich
    "",                      # leer
    "a" * 129,               # 129 Zeichen
    2026,                    # keine Zeichenkette
])
def test_die_form_des_auftragsschluessels(schluessel, wert):
    """Regel 2: dieselbe Form wie § 8a - ein Schluessel ausserhalb ihrer ist
    keiner, nach dem nicht gesucht wird."""
    urteil = _urteil(schluessel, aufstellungsauftrag(auftragsschluessel=wert))

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", "$.nutzlast.auftragsschluessel")]


def test_zum_schluessel_gerechnet_ist_keine_zweite_aufstellung(schluessel):
    """Regel 2: Der Auftragsschluessel schuetzt wie in § 8a vor der zweiten
    Aufstellung zum selben Auftrag; ein Entwurf zaehlt als gerechnet."""
    urteil = _urteil(
        schluessel, aufstellungsauftrag(),
        lage=_Lage(dokumente={SCHLUESSEL_IM_BELEG: "Entwurf"},
                   partner=(PARTNER_A,), anlagen=probe_anlagen()),
    )

    feststellung, = urteil.feststellungen
    assert (feststellung.code, feststellung.pfad, feststellung.erhalten) == (
        "AUFTRAG_SCHON_GERECHNET", "$.nutzlast.auftragsschluessel", "Entwurf",
    )


def test_der_kunde_muss_im_stamm_stehen(schluessel):
    """Regel 2: § 8b wie § 8a - der Auszahler hinter partner_id, ohne ihn
    gibt es niemanden, dem die Aufstellung zugeordnet waere."""
    urteil = _urteil(schluessel, aufstellungsauftrag(), lage=_Lage())

    assert _befunde(urteil) == [("PARTNER_ID_UNBEKANNT", "$.nutzlast.kunde.partner_id")]


@pytest.mark.parametrize("zeitraum", [
    {"von": "2026-01-01", "bis": "2026-02-28"},  # zwei Monate
    {"von": "2026-02-02", "bis": "2026-02-28"},  # von ist nicht der Erste
    {"von": "2026-02-01", "bis": "2026-02-27"},  # bis ist nicht der Letzte
])
def test_der_leistungszeitraum_ist_genau_ein_kalendermonat(schluessel, zeitraum):
    """Regel 2: dieselbe Monatsregel wie § 8a - wer sammelt, verliert die
    Zuordnung zur Zahlung."""
    urteil = _urteil(schluessel, aufstellungsauftrag(leistungszeitraum=zeitraum))

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.leistungszeitraum"),
    ]


# ---- Regel 3: waehrung und betraege ----


@pytest.mark.parametrize("wert", [
    "usd",     # Kleinbuchstaben sind eine andere Form
    "US",      # zwei Buchstaben
    "USDD",    # vier Buchstaben
    42,        # keine Zeichenkette
])
def test_die_waehrung_ist_drei_grossbuchstaben(schluessel, wert):
    """Regel 3: ISO 4217 als Form, aber kein Wertevorrat - ein Vorrat
    stuende im oeffentlichen Code dieses Empfaengers."""
    urteil = _urteil(schluessel, aufstellungsauftrag(waehrung=wert))

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", "$.nutzlast.waehrung")]


@pytest.mark.parametrize("pfad, aenderung", [
    ("$.nutzlast.betraege.brutto", {"betraege": {
        "brutto": "6.9", "quellensteuer": "2.08", "netto": "4.84"}}),
    ("$.nutzlast.umrechnung.zahlbetrag", {"umrechnung": {
        "kurs": "0.8533", "waehrung": "EUR", "zahlbetrag": "4.1"}}),
])
def test_die_geldform_gilt_zentral_weiter(schluessel, pfad, aenderung):
    """Regel 3: dieselbe Formprobe des § 4 (protokoll.FELDFORMEN), keine
    zweite - auch keine Kopie an dieser Art."""
    urteil = _urteil(schluessel, aufstellungsauftrag(**aenderung))

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", pfad)]


def test_die_betraege_muessen_aufgehen(schluessel):
    """Regel 3: brutto - quellensteuer == netto, exakt ohne Toleranz - ein
    Cent daneben ist keiner."""
    nutzlast = aufstellungsauftrag(betraege={
        "brutto": "6.92", "quellensteuer": "2.08", "netto": "4.85",
    })

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("SUMME_STIMMT_NICHT", "$.nutzlast.betraege.netto")]


def test_die_quellensteuer_ist_nie_negativ(schluessel):
    """Regel 3: Ein Einbehalt des Auszahlers ist nie negativ. Die Betraege
    gehen auf (5.84 - (-1.00) = 6.84), und gerade deshalb faellt es sonst
    nicht auf."""
    nutzlast = aufstellungsauftrag(betraege={
        "brutto": "5.84", "quellensteuer": "-1.00", "netto": "6.84",
    })

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("SUMME_STIMMT_NICHT", "$.nutzlast.betraege.quellensteuer"),
    ]


def test_eine_aufstellung_ueber_nichts_ist_keine(schluessel):
    """Regel 3: Die Betraege gehen auf (2.08 - 2.08 = 0.00), aber ueber null
    stellt niemand eine Aufstellung. Unbrauchbar ist der Wert: Der Sender
    bildet netto aus brutto und quellensteuer."""
    nutzlast = aufstellungsauftrag(betraege={
        "brutto": "2.08", "quellensteuer": "2.08", "netto": "0.00",
    })

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", "$.nutzlast.betraege.netto")]


# ---- Regel 4: umrechnung ----


def test_bei_fremdwaehrung_ist_die_umrechnung_pflicht(schluessel):
    """Regel 4: umrechnung genau dann, wenn waehrung nicht EUR ist - fehlt
    sie bei USD, weiss niemand, was ausgezahlt wurde."""
    nutzlast = aufstellungsauftrag()
    del nutzlast["umrechnung"]

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("PFLICHTFELD_FEHLT", "$.nutzlast.umrechnung")]


def test_bei_euro_gibt_es_nichts_umzurechnen(schluessel):
    """Regel 4: Bei EUR ist die umrechnung ein Feld zu viel - kein
    UNBEKANNTES_FELD des Verzeichnisses, denn dort steht sie als erlaubt;
    die genau-dann-Regel macht sie unbekannt."""
    urteil = _urteil(schluessel, aufstellungsauftrag(waehrung="EUR"))

    assert _befunde(urteil) == [("UNBEKANNTES_FELD", "$.nutzlast.umrechnung")]


def test_bei_euro_ohne_umrechnung_wird_angenommen(schluessel):
    """Regel 4: Die andere Seite der genau-dann-Regel - EUR ohne umrechnung
    ist der Normalfall des Inlands und wird angenommen."""
    nutzlast = aufstellungsauftrag(waehrung="EUR")
    del nutzlast["umrechnung"]

    urteil = _urteil(schluessel, nutzlast)

    assert urteil.angenommen, _befunde(urteil)


@pytest.mark.parametrize("kurs", [
    "0,8533",   # Komma ist kein Dezimalpunkt
    "8533",     # ohne Dezimalpunkt
    1,          # keine Zeichenkette
])
def test_der_kurs_ist_ein_dezimalbruch_als_zeichenkette(schluessel, kurs):
    """Regel 4: so viele Nachkommastellen wie gedruckt - weder Geldform
    (genau zwei) noch Satzform (mindestens zwei), denn der Kurs steht
    drauf, wie ihn die Plattform nennt."""
    nutzlast = aufstellungsauftrag(umrechnung={
        "kurs": kurs, "waehrung": "EUR", "zahlbetrag": "4.13",
    })

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", "$.nutzlast.umrechnung.kurs")]


def test_umgerechnet_wird_nur_nach_euro(schluessel):
    """Regel 4: Dieser Empfaenger rechnet in Euro; eine Zielwaehrung
    ausserhalb waere eine zweite Umrechnung, die niemand bestellt hat."""
    nutzlast = aufstellungsauftrag(umrechnung={
        "kurs": "0.8533", "waehrung": "USD", "zahlbetrag": "4.13",
    })

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.umrechnung.waehrung"),
    ]


def test_die_gleichung_der_umrechnung_wird_nicht_geprueft(schluessel):
    """Regel 4: netto x kurs == zahlbetrag wird NICHT geprueft - die
    Plattform rechnet die Umrechnung, eine Abweichung waere eine gedruckte
    Tatsache. 4.84 x 0.8533 sind 4.13, hier steht 9.99, und das ist angenommen."""
    nutzlast = aufstellungsauftrag(umrechnung={
        "kurs": "0.8533", "waehrung": "EUR", "zahlbetrag": "9.99",
    })

    urteil = _urteil(schluessel, nutzlast)

    assert urteil.angenommen, _befunde(urteil)


# ---- Regel 5: zahlung ----


@pytest.mark.parametrize("nummer", [
    "100000000000001.0",   # die xlsx speichert sie als Gleitkommazahl
    "100 000 000 000 001",
    100000000000001,       # keine Zeichenkette
])
def test_die_zahlungsnummer_ist_eine_ziffernfolge(schluessel, nummer):
    """Regel 5: Eine Kennung, keine Zahl - wer sie parst, verliert die
    Fuehrenden Nullen und verwechselt zwei Zahlungen."""
    nutzlast = aufstellungsauftrag(zahlung={
        "zahlungsnummer": nummer, "datum": "2026-04-29",
    })

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.zahlung.zahlungsnummer"),
    ]


def test_das_zahlungsdatum_ist_ein_datum(schluessel):
    """Regel 5: Gelesen mit derselben Regel wie jeder Zeitraum des Formats
    (date.fromisoformat), damit kein gueltiger Auftrag abgelehnt wird."""
    nutzlast = aufstellungsauftrag(zahlung={
        "zahlungsnummer": "100000000000001", "datum": "29.04.2026",
    })

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.zahlung.datum"),
    ]


# ---- Regel 6: die anlagen als Werte ----


@pytest.mark.parametrize("aenderung", [
    {"anlagen": []},
    {"anlagen": [anlage("abrechnungsbericht", "bericht.xlsx", ANLAGE_ABRECHNUNGSBERICHT)]},
    {"anlagen": [
        anlage("abrechnungsbericht", "b1.xlsx", ANLAGE_ABRECHNUNGSBERICHT),
        anlage("abrechnungsbericht", "b2.xlsx", ANLAGE_ZAHLUNGSBERICHT),
    ]},
    {"anlagen": [
        anlage("abrechnungsbericht", "b1.xlsx", ANLAGE_ABRECHNUNGSBERICHT),
        anlage("zahlungsbericht", "b2.xlsx", ANLAGE_ZAHLUNGSBERICHT),
        anlage("zahlungsbericht", "b3.xlsx", ANLAGE_ABRECHNUNGSBERICHT),
    ]},
])
def test_genau_zwei_anlagen_je_quelle(schluessel, aenderung):
    """Regel 6: GENAU zwei, je eine aus abrechnungsbericht und
    zahlungsbericht. Eine andere Anzahl ist WERT_UNBRAUCHBAR und nicht
    PFLICHTFELD_FEHLT: Das Feld ist da, seine Besetzung taugt nicht - auch
    die leere Liste, denn anlagen zaehlt nicht zu _LEER_IST_FEHLEND."""
    urteil = _urteil(schluessel, aufstellungsauftrag(**aenderung))

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", "$.nutzlast.anlagen")]


def test_der_sha_einer_anlage_ist_kleinbuchstaben_hex(schluessel):
    """Regel 6: 64 Kleinbuchstaben-Hex, wie hashlib.hexdigest() ihn bildet -
    der Name der Datei ist zugleich ihr Ort."""
    nutzlast = aufstellungsauftrag()
    nutzlast["anlagen"][0]["sha256"] = "1A" * 32

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.anlagen[0].sha256"),
    ]


@pytest.mark.parametrize("groesse", [
    0,             # eine leere Datei ist keine Anlage
    20000001,      # ueber der Schutzgrenze des Lesers
    "32",          # keine Ganzzahl
    True,          # in Python eine Ganzzahl, aber keine Groesse
])
def test_die_groesse_einer_anlage(schluessel, groesse):
    """Regel 6: eine Ganzzahl von 1 bis 20 000 000 - Schutzgrenze fuer den
    Leser, keine Aussage ueber einen Versandweg."""
    nutzlast = aufstellungsauftrag()
    nutzlast["anlagen"][1]["groesse"] = groesse

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.anlagen[1].groesse"),
    ]


def test_der_medientyp_ist_nur_xlsx(schluessel):
    """Regel 6: In 1.7 ist nur der xlsx-Typ bekannt; die Datei liegt und
    passt, es ist der Wert, der nicht taugt."""
    nutzlast = aufstellungsauftrag()
    nutzlast["anlagen"][1]["medientyp"] = "application/pdf"

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.anlagen[1].medientyp"),
    ]


def test_der_dateiname_ist_freier_text(schluessel):
    """Regel 6: Keine Probe. Der Name nennt vielleicht eine Plattform oder
    eine Firma, und abgehakt ist oeffentlich - solche Namen reisen als freie
    Daten."""
    nutzlast = aufstellungsauftrag()
    nutzlast["anlagen"][0]["dateiname"] = "Plattform Bericht, Februar.xlsx"

    urteil = _urteil(schluessel, nutzlast)

    assert urteil.angenommen, _befunde(urteil)


# ---- Regel 7: die Dateien ----


def test_eine_fehlende_anlage_wird_gemeldet(schluessel):
    """Regel 7: Die Anlage liegt unter anlagen/<sha256>.xlsx - fehlt sie,
    gibt es keinen Zwischenzustand: Die Anlagen werden vor dem Beleg
    geschrieben. Jede Anlage ist ihr eigener Grund."""
    anlagen = probe_anlagen()
    del anlagen[aufstellungsauftrag()["anlagen"][1]["sha256"]]

    urteil = _urteil(
        schluessel, aufstellungsauftrag(),
        lage=_Lage(partner=(PARTNER_A,), anlagen=anlagen),
    )

    assert _befunde(urteil) == [("ANLAGE_FEHLT", "$.nutzlast.anlagen[1]")]


def test_ohne_jede_anlage_werden_beide_gemeldet(schluessel):
    """Regel 7: JE Grund einen Befund - eine leere Ablage macht aus einem
    Beleg zwei Grunde, nicht einen."""
    urteil = _urteil(
        schluessel, aufstellungsauftrag(),
        lage=_Lage(partner=(PARTNER_A,), anlagen={}),
    )

    assert _befunde(urteil) == [
        ("ANLAGE_FEHLT", "$.nutzlast.anlagen[0]"),
        ("ANLAGE_FEHLT", "$.nutzlast.anlagen[1]"),
    ]


def test_eine_anlage_mit_anderem_inhalt(schluessel):
    """Regel 7: Die Datei liegt unter dem genannten Namen, gleich gross,
    aber ein Zeichen anders. Wer nur die Existenz prueft, nimmt sie an."""
    nutzlast = aufstellungsauftrag()
    sha = nutzlast["anlagen"][1]["sha256"]
    falsch = _Lage(
        partner=(PARTNER_A,),
        anlagen={**probe_anlagen(), sha: ANLAGE_ZAHLUNGSBERICHT + b"x"},
    )

    urteil = _urteil(schluessel, nutzlast, lage=falsch)

    assert _befunde(urteil) == [
        ("ANLAGE_HASH_FALSCH", "$.nutzlast.anlagen[1].sha256"),
    ]


def test_eine_anlage_mit_anderer_groesse(schluessel):
    """Regel 7: Hash stimmt, groesse weicht ab - derselbe Befundcode, denn
    beides sagt: Die Datei ist nicht die, die der Eintrag nennt."""
    nutzlast = aufstellungsauftrag()
    nutzlast["anlagen"][1]["groesse"] = len(ANLAGE_ZAHLUNGSBERICHT) + 1

    urteil = _urteil(
        schluessel, nutzlast,
        lage=_Lage(partner=(PARTNER_A,), anlagen=probe_anlagen()),
    )

    assert _befunde(urteil) == [
        ("ANLAGE_HASH_FALSCH", "$.nutzlast.anlagen[1].groesse"),
    ]


def test_die_dateien_werden_erst_nach_den_werten_geprueft(schluessel):
    """Regel 7: Nur ein in sich brauchbarer Beleg wird gegen die Dateien
    gehalten - sonst hiesse der Befund ANLAGE_FEHLT, obwohl der Absender
    zuerst die Nutzlast reparieren muss."""
    nutzlast = aufstellungsauftrag(betraege={
        "brutto": "6.92", "quellensteuer": "2.08", "netto": "4.85",
    })

    urteil = _urteil(schluessel, nutzlast, lage=_Lage(partner=(PARTNER_A,)))

    assert _befunde(urteil) == [("SUMME_STIMMT_NICHT", "$.nutzlast.betraege.netto")]
