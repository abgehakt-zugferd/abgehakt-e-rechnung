"""Gemeinsame Formprobe fuer Uebergabe-Zeichenketten (#210).

`re.match` mit einem Muster, das auf `$` endet, trifft auch vor einem
abschliessenden Zeilenende. `fullmatch` verlangt die ganze Zeichenkette:
`probe:1\\n` ist dann ein anderer, unbrauchbarer Wert als `probe:1`.
Auch Decimal nimmt `"174.33\\n"` anstandslos; ohne die Formprobe waere der
Betrag gerechnet und der Auftragsschluessel an AUFTRAG_SCHON_GERECHNET
vorbeigeschlichen.
"""

import re
from typing import Pattern, Union

# § 4, je Form EINE Pruefung und an EINER Stelle angewandt (protokoll.FELDFORMEN
# nennt die Felder). Geld ist eine JSON-Zeichenkette mit Dezimalpunkt und GENAU
# zwei Nachkommastellen - Decimal haette "174.3300", " 174.33" und "1.7433E2"
# still geschluckt, und die Wirkung rundete dann heimlich. Das optionale
# fuehrende Minus bleibt: kein Feld des Auftrags hat dem Leser bisher ein
# Vorzeichen verboten, und die Formprobe aendert am Vorzeichen nichts.
GELDFORM = re.compile(r"^-?[0-9]+\.[0-9]{2}$")

# Der Satz ist vom Geld getrennt (Klarstellung 2026-10-17): MINDESTENS zwei
# Nachkommastellen, denn ein Satz, der vorher gerundet wird, lehnt den
# gueltigen Auftrag ab (siehe _zahl in uebergabe_befund).
SATZFORM = re.compile(r"^-?[0-9]+\.[0-9]{2,}$")

# § 8a, Teil 1b: die Formen der grundlagen[]. beleg_sha256 ist der Hash des
# Abrechnungsberichts, klein wie hashlib.hexdigest() ihn bildet - Grossbuchstaben
# sind eine andere Form, kein anderer Wert. leistungsperiode ist ein Monat
# JJJJ-MM, kein Quartal und kein Zeitraum.
SHA256_FORM = re.compile(r"^[0-9a-f]{64}$")
MONAT_FORM = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")

# § 8a, Teil 1c: die Form des auftragsschluessels - kleine Buchstaben,
# Ziffern, Doppelpunkt und Bindestrich, 1 bis 128 Zeichen. Grossbuchstaben
# und Leerzeichen sind eine andere Form: Der Schluessel wird gezeichnet und
# verglichen, nicht gelesen, und ein anderer Zeichenvorrat machte den
# Vergleich zweier Umsetzungen vom Zufall der Gross- und Kleinschreibung
# abhaengig. Die Form steht hier und nicht in FELDFORMEN, denn dort stehen
# die Geld- und Satzformen des § 4, die JEDE Art betreffen.
AUFTRAGSSCHLUESSEL_FORM = re.compile(r"^[a-z0-9:-]{1,128}$")

# § 8b: die Formen, die nur der aufstellungsauftrag liest. Die waehrung ist
# ISO 4217 als Form, aber ohne Wertevorrat - ein Vorrat stuende im
# oeffentlichen Code dieses Empfaengers. Der kurs ist weder Geld (genau zwei
# Nachkommastellen) noch Satz (mindestens zwei): Er steht drauf, wie ihn die
# Plattform nennt. Die zahlungsnummer ist eine Kennung aus Ziffern, keine
# Zahl - die xlsx speichert sie als Gleitkommazahl, und
# '100000000000001.0' ist ein anderer Wert.
WAEHRUNG_FORM = re.compile(r"^[A-Z]{3}$")
KURS_FORM = re.compile(r"^[0-9]+\.[0-9]+$")
ZAHLUNGSNUMMER_FORM = re.compile(r"^[0-9]+$")

# JJJJ-MM-TT mit Bindestrichen. date.fromisoformat nimmt unter Python 3.11
# auch 20261001 an; die Formprobe steht davor.
DATUM_FORM = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def ganz_passt(muster: Union[Pattern[str], str], wert) -> bool:
    """True nur wenn `wert` eine Zeichenkette ist und `muster` sie ganz trifft."""
    if not isinstance(wert, str):
        return False
    if isinstance(muster, str):
        return re.fullmatch(muster, wert) is not None
    return muster.fullmatch(wert) is not None
