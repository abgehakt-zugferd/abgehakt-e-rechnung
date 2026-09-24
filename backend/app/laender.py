"""Laenderlisten fuer die Landesauswahl in den Formularen (#75, #81).

Bis hierher schrieben die drei Formulare mit Landfeld (Kunde, Einstellungen,
Einrichtung) ihre Optionen selbst aus und kannten nur DE, AT, CH und US: ein
Kunde in Finnland liess sich ueber die Oberflaeche nicht anlegen. Wie bei
`branding` und `darstellung` gilt: jeder Router erzeugt sein eigenes
Jinja-Environment, es gibt keinen gemeinsamen Context-Processor. Deshalb
stehen die Listen genau einmal hier, und `registriere_laender_globals` gibt
sie je Instanz in die Environments der drei Router, die ein Landfeld rendern.

`LAENDER` (47) ist die kuratierte Liste fuer das Kundenformular: EU-27,
europaeische Nicht-EU-Staaten, US. `ISO_LAENDER` (249) ist die volle
ISO-3166-1-alpha-2-Liste fuer Einrichtung und Einstellungen; ohne sie
liess sich ein Aussteller mit Sitz ausserhalb der 47 nicht mehr einrichten
(#81).

Gespeichert wird der ISO-3166-1-alpha-2-Code (`String(2)` am Modell); er
laeuft unveraendert in `ram:CountryID` der ZUGFeRD-XML. Griechenland traegt
hier `GR` (ISO); dass VIES Griechenland als `EL` kennt, bildet allein
`services/ust_id_pruefung._VIES_LAENDER` ab, diese Abbildung wird hier nicht
verdoppelt.

Reihenfolge: DE zuerst (Regelfall der Installationen), danach alphabetisch
nach deutschem Namen. Wache: tests/test_laender.py.

## Herkunft von ISO_LAENDER (nicht aus dem Gedaechtnis)

Eingebettete Tabelle statt Laufzeitabhaengigkeit: `pycountry` (~7,8 MB) und
`babel` (~10 MB) wuerden das Auslieferungsabbild nur fuer Anzeigenamen
aufblasen; die Codes aendern sich selten, die deutschen Namen noch seltener.

- Codes: die 249 offiziell vergebenen alpha-2-Eintraege aus dem Debian-
  Paket iso-codes (`data/iso_3166-1.json` der iso-codes-Quellen,
  https://salsa.debian.org/iso-codes-team/iso-codes). Stand der Erzeugung:
  2026-09-23.
- Deutsche Namen: Unicode CLDR locale `de`, Datei
  `cldr-localenames-full/main/de/territories.json`
  (https://github.com/unicode-org/cldr-json). Pseudo-Regionen und
  Ausnahme-Reservierungen, die CLDR zusaetzlich fuehrt (EU, UN, XK, …),
  sind bewusst nicht enthalten: sie stehen nicht in ISO 3166-1.
- Namensgleichheit mit `LAENDER`: fuer jeden Code aus `LAENDER` gilt der
  dort kuratierte Name (z. B. MD = „Moldau“, nicht CLDR „Republik Moldau“),
  damit die beiden Listen nicht auseinanderlaufen. Der Drift-Test haelt das.

Nachziehen: iso-codes-JSON und CLDR-territories.json laden, auf die
Schnittmenge der 249 alpha-2-Codes einschraenken, `LAENDER`-Namen
ueberschreiben, DE zuerst und Rest nach deutscher Faltung sortieren, dieses
Tupel ersetzen. Die Zahl der Eintraege muss der Quelle folgen; der Test
nennt sie.
"""
import unicodedata

from fastapi.templating import Jinja2Templates

LAENDER: tuple[tuple[str, str], ...] = (
    ("DE", "Deutschland"),
    ("AL", "Albanien"),
    ("AD", "Andorra"),
    ("BY", "Belarus"),
    ("BE", "Belgien"),
    ("BA", "Bosnien und Herzegowina"),
    ("BG", "Bulgarien"),
    ("DK", "Dänemark"),
    ("EE", "Estland"),
    ("FI", "Finnland"),
    ("FR", "Frankreich"),
    ("GR", "Griechenland"),
    ("IE", "Irland"),
    ("IS", "Island"),
    ("IT", "Italien"),
    ("HR", "Kroatien"),
    ("LV", "Lettland"),
    ("LI", "Liechtenstein"),
    ("LT", "Litauen"),
    ("LU", "Luxemburg"),
    ("MT", "Malta"),
    ("MD", "Moldau"),
    ("MC", "Monaco"),
    ("ME", "Montenegro"),
    ("NL", "Niederlande"),
    ("MK", "Nordmazedonien"),
    ("NO", "Norwegen"),
    ("AT", "Österreich"),
    ("PL", "Polen"),
    ("PT", "Portugal"),
    ("RO", "Rumänien"),
    ("RU", "Russland"),
    ("SM", "San Marino"),
    ("SE", "Schweden"),
    ("CH", "Schweiz"),
    ("RS", "Serbien"),
    ("SK", "Slowakei"),
    ("SI", "Slowenien"),
    ("ES", "Spanien"),
    ("CZ", "Tschechien"),
    ("TR", "Türkei"),
    ("UA", "Ukraine"),
    ("HU", "Ungarn"),
    ("VA", "Vatikanstadt"),
    ("US", "Vereinigte Staaten"),
    ("GB", "Vereinigtes Königreich"),
    ("CY", "Zypern"),
)



ISO_LAENDER: tuple[tuple[str, str], ...] = (
    ("DE", "Deutschland"),
    ("AF", "Afghanistan"),
    ("EG", "Ägypten"),
    ("AX", "Ålandinseln"),
    ("AL", "Albanien"),
    ("DZ", "Algerien"),
    ("AS", "Amerikanisch-Samoa"),
    ("VI", "Amerikanische Jungferninseln"),
    ("UM", "Amerikanische Überseeinseln"),
    ("AD", "Andorra"),
    ("AO", "Angola"),
    ("AI", "Anguilla"),
    ("AQ", "Antarktis"),
    ("AG", "Antigua und Barbuda"),
    ("GQ", "Äquatorialguinea"),
    ("AR", "Argentinien"),
    ("AM", "Armenien"),
    ("AW", "Aruba"),
    ("AZ", "Aserbaidschan"),
    ("ET", "Äthiopien"),
    ("AU", "Australien"),
    ("BS", "Bahamas"),
    ("BH", "Bahrain"),
    ("BD", "Bangladesch"),
    ("BB", "Barbados"),
    ("BY", "Belarus"),
    ("BE", "Belgien"),
    ("BZ", "Belize"),
    ("BJ", "Benin"),
    ("BM", "Bermuda"),
    ("BT", "Bhutan"),
    ("BO", "Bolivien"),
    ("BA", "Bosnien und Herzegowina"),
    ("BW", "Botsuana"),
    ("BV", "Bouvetinsel"),
    ("BR", "Brasilien"),
    ("VG", "Britische Jungferninseln"),
    ("IO", "Britisches Territorium im Indischen Ozean"),
    ("BN", "Brunei Darussalam"),
    ("BG", "Bulgarien"),
    ("BF", "Burkina Faso"),
    ("BI", "Burundi"),
    ("CV", "Cabo Verde"),
    ("CL", "Chile"),
    ("CN", "China"),
    ("CK", "Cookinseln"),
    ("CR", "Costa Rica"),
    ("CI", "Côte d’Ivoire"),
    ("CW", "Curaçao"),
    ("DK", "Dänemark"),
    ("DM", "Dominica"),
    ("DO", "Dominikanische Republik"),
    ("DJ", "Dschibuti"),
    ("EC", "Ecuador"),
    ("SV", "El Salvador"),
    ("ER", "Eritrea"),
    ("EE", "Estland"),
    ("SZ", "Eswatini"),
    ("FK", "Falklandinseln"),
    ("FO", "Färöer"),
    ("FJ", "Fidschi"),
    ("FI", "Finnland"),
    ("FR", "Frankreich"),
    ("GF", "Französisch-Guayana"),
    ("PF", "Französisch-Polynesien"),
    ("TF", "Französische Süd- und Antarktisgebiete"),
    ("GA", "Gabun"),
    ("GM", "Gambia"),
    ("GE", "Georgien"),
    ("GH", "Ghana"),
    ("GI", "Gibraltar"),
    ("GD", "Grenada"),
    ("GR", "Griechenland"),
    ("GL", "Grönland"),
    ("GP", "Guadeloupe"),
    ("GU", "Guam"),
    ("GT", "Guatemala"),
    ("GG", "Guernsey"),
    ("GN", "Guinea"),
    ("GW", "Guinea-Bissau"),
    ("GY", "Guyana"),
    ("HT", "Haiti"),
    ("HM", "Heard und McDonaldinseln"),
    ("HN", "Honduras"),
    ("IN", "Indien"),
    ("ID", "Indonesien"),
    ("IQ", "Irak"),
    ("IR", "Iran"),
    ("IE", "Irland"),
    ("IS", "Island"),
    ("IM", "Isle of Man"),
    ("IL", "Israel"),
    ("IT", "Italien"),
    ("JM", "Jamaika"),
    ("JP", "Japan"),
    ("YE", "Jemen"),
    ("JE", "Jersey"),
    ("JO", "Jordanien"),
    ("KY", "Kaimaninseln"),
    ("KH", "Kambodscha"),
    ("CM", "Kamerun"),
    ("CA", "Kanada"),
    ("BQ", "Karibische Niederlande"),
    ("KZ", "Kasachstan"),
    ("QA", "Katar"),
    ("KE", "Kenia"),
    ("KG", "Kirgisistan"),
    ("KI", "Kiribati"),
    ("CC", "Kokosinseln"),
    ("CO", "Kolumbien"),
    ("KM", "Komoren"),
    ("CG", "Kongo-Brazzaville"),
    ("CD", "Kongo-Kinshasa"),
    ("HR", "Kroatien"),
    ("CU", "Kuba"),
    ("KW", "Kuwait"),
    ("LA", "Laos"),
    ("LS", "Lesotho"),
    ("LV", "Lettland"),
    ("LB", "Libanon"),
    ("LR", "Liberia"),
    ("LY", "Libyen"),
    ("LI", "Liechtenstein"),
    ("LT", "Litauen"),
    ("LU", "Luxemburg"),
    ("MG", "Madagaskar"),
    ("MW", "Malawi"),
    ("MY", "Malaysia"),
    ("MV", "Malediven"),
    ("ML", "Mali"),
    ("MT", "Malta"),
    ("MA", "Marokko"),
    ("MH", "Marshallinseln"),
    ("MQ", "Martinique"),
    ("MR", "Mauretanien"),
    ("MU", "Mauritius"),
    ("YT", "Mayotte"),
    ("MX", "Mexiko"),
    ("FM", "Mikronesien"),
    ("MD", "Moldau"),
    ("MC", "Monaco"),
    ("MN", "Mongolei"),
    ("ME", "Montenegro"),
    ("MS", "Montserrat"),
    ("MZ", "Mosambik"),
    ("MM", "Myanmar"),
    ("NA", "Namibia"),
    ("NR", "Nauru"),
    ("NP", "Nepal"),
    ("NC", "Neukaledonien"),
    ("NZ", "Neuseeland"),
    ("NI", "Nicaragua"),
    ("NL", "Niederlande"),
    ("NE", "Niger"),
    ("NG", "Nigeria"),
    ("NU", "Niue"),
    ("KP", "Nordkorea"),
    ("MP", "Nördliche Marianen"),
    ("MK", "Nordmazedonien"),
    ("NF", "Norfolkinsel"),
    ("NO", "Norwegen"),
    ("OM", "Oman"),
    ("AT", "Österreich"),
    ("PK", "Pakistan"),
    ("PS", "Palästinensische Autonomiegebiete"),
    ("PW", "Palau"),
    ("PA", "Panama"),
    ("PG", "Papua-Neuguinea"),
    ("PY", "Paraguay"),
    ("PE", "Peru"),
    ("PH", "Philippinen"),
    ("PN", "Pitcairninseln"),
    ("PL", "Polen"),
    ("PT", "Portugal"),
    ("PR", "Puerto Rico"),
    ("RE", "Réunion"),
    ("RW", "Ruanda"),
    ("RO", "Rumänien"),
    ("RU", "Russland"),
    ("SB", "Salomonen"),
    ("ZM", "Sambia"),
    ("WS", "Samoa"),
    ("SM", "San Marino"),
    ("ST", "São Tomé und Príncipe"),
    ("SA", "Saudi-Arabien"),
    ("SE", "Schweden"),
    ("CH", "Schweiz"),
    ("SN", "Senegal"),
    ("RS", "Serbien"),
    ("SC", "Seychellen"),
    ("SL", "Sierra Leone"),
    ("ZW", "Simbabwe"),
    ("SG", "Singapur"),
    ("SX", "Sint Maarten"),
    ("SK", "Slowakei"),
    ("SI", "Slowenien"),
    ("SO", "Somalia"),
    ("HK", "Sonderverwaltungsregion Hongkong"),
    ("MO", "Sonderverwaltungsregion Macau"),
    ("ES", "Spanien"),
    ("SJ", "Spitzbergen und Jan Mayen"),
    ("LK", "Sri Lanka"),
    ("BL", "St. Barthélemy"),
    ("SH", "St. Helena"),
    ("KN", "St. Kitts und Nevis"),
    ("LC", "St. Lucia"),
    ("MF", "St. Martin"),
    ("PM", "St. Pierre und Miquelon"),
    ("VC", "St. Vincent und die Grenadinen"),
    ("ZA", "Südafrika"),
    ("SD", "Sudan"),
    ("GS", "Südgeorgien und die Südlichen Sandwichinseln"),
    ("KR", "Südkorea"),
    ("SS", "Südsudan"),
    ("SR", "Suriname"),
    ("SY", "Syrien"),
    ("TJ", "Tadschikistan"),
    ("TW", "Taiwan"),
    ("TZ", "Tansania"),
    ("TH", "Thailand"),
    ("TL", "Timor-Leste"),
    ("TG", "Togo"),
    ("TK", "Tokelau"),
    ("TO", "Tonga"),
    ("TT", "Trinidad und Tobago"),
    ("TD", "Tschad"),
    ("CZ", "Tschechien"),
    ("TN", "Tunesien"),
    ("TR", "Türkei"),
    ("TM", "Turkmenistan"),
    ("TC", "Turks- und Caicosinseln"),
    ("TV", "Tuvalu"),
    ("UG", "Uganda"),
    ("UA", "Ukraine"),
    ("HU", "Ungarn"),
    ("UY", "Uruguay"),
    ("UZ", "Usbekistan"),
    ("VU", "Vanuatu"),
    ("VA", "Vatikanstadt"),
    ("VE", "Venezuela"),
    ("AE", "Vereinigte Arabische Emirate"),
    ("US", "Vereinigte Staaten"),
    ("GB", "Vereinigtes Königreich"),
    ("VN", "Vietnam"),
    ("WF", "Wallis und Futuna"),
    ("CX", "Weihnachtsinsel"),
    ("EH", "Westsahara"),
    ("CF", "Zentralafrikanische Republik"),
    ("CY", "Zypern"),
)



def sortierschluessel(name: str) -> str:
    """Sortierschluessel nach deutscher Alphabet-Ordnung (Umlaut = Grundbuchstabe).

    Zwei Schritte, und der zweite fehlte: Erst die deutschen Sonderzeichen nach
    DIN 5007-1 (ae wie a, ss wie ss), dann alle uebrigen diakritischen Zeichen
    ueber die Zerlegung. Ohne den zweiten landete Ålandinseln hinter Zypern,
    weil `å` in Unicode hinter `z` liegt. Buchstaben, die keine Zerlegung
    haben, brauchen eine eigene Zeile: æ, ø, đ, ð, þ, ł.
    """
    gefaltet = (
        name.casefold()
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("ü", "u")
        .replace("ß", "ss")
        .replace("æ", "ae")
        .replace("ø", "o")
        .replace("đ", "d")
        .replace("ð", "d")
        .replace("þ", "th")
        .replace("ł", "l")
    )
    zerlegt = unicodedata.normalize("NFD", gefaltet)
    return "".join(z for z in zerlegt if not unicodedata.combining(z))


def registriere_laender_globals(templates: Jinja2Templates) -> None:
    """Macht `LAENDER` und `ISO_LAENDER` in einem Jinja-Environment verfügbar.

    Muss JEDE Instanz einzeln bekommen, die ein Landfeld rendert (Kunden,
    Einstellungen, Einrichtung) — dieselbe Lage wie bei
    `branding.register_branding_globals`. Ein hier vergessener Router fällt
    nicht beim Start auf, sondern erst beim Aufruf seiner Seite.
    """
    templates.env.globals["LAENDER"] = LAENDER
    templates.env.globals["ISO_LAENDER"] = ISO_LAENDER
