# Fachliche Spezifikation: IBAN-Pruefung

## Zweck und Geltungsbereich

Diese Spezifikation behebt zwei getrennte Fehlerquellen:

1. Eine eingegebene IBAN darf nicht allein wegen Zeichenvorrat und Gesamtlänge als gültig gelten. Sie muss die ISO-13616-Prüfziffer erfüllen und, für bekannte Länder, die veröffentlichte Landeslänge haben.
2. Die Datenwache darf nicht mehr nur deutsche, zufällig ähnlich aussehende Zeichenfolgen finden. Sie muss länderübergreifend Kandidaten erkennen, deren Prüfziffer prüfen und klar markierte, konstruierte Testwerte ausnehmen.

Der Geltungsbereich umfasst die Eingabe von `Company.bank_iban` und `Customer.bank_iban`, die Normalisierung, den sichtbaren PDF-Zahlungshinweis, `ram:IBANID` in der ZUGFeRD-XML, den EPC-QR-Payload und `.githooks/datenwache.sh`. Es ist keine Kontoinhaber-, Bank-, BIC- oder Erreichbarkeitsprüfung. Eine bestandene IBAN-Prüfziffer beweist insbesondere nicht, dass ein Konto existiert oder dem angegebenen Empfänger gehört.

## Quellenstand und Begriffe

Die normative Quelle für nationale Formate ist das [SWIFT IBAN Registry, Release 103, September 2026](https://www.swift.com/swift-resource/9606/download). Der Titel nennt Release und Monat; die Fassung enthält 89 ISO-13616-konforme nationale Formate und führt ISO 13616-1 sowie ISO/IEC 7064 als Referenzen. SWIFT ist die von ISO benannte Registrierungsstelle und beschreibt das Registry selbst als technische Spezifikation nationaler, ISO-13616-konformer Formate: [SWIFT, IBAN](https://www.swift.com/standards/data-standards/iban-international-bank-account-number).

Für den QR-Kontext ist [EPC069-12, Version 3.1, 19. März 2024](https://www.europeanpaymentscouncil.eu/sites/default/files/kb/file/2024-03/EPC069-12%20v3.1%20Quick%20Response%20Code%20-%20Guidelines%20to%20Enable%20the%20Data%20Capture%20for%20the%20Initiation%20of%20an%20SCT.pdf) maßgeblich. Er fordert für das Konto des Begünstigten eine IBAN, maximal 34 Zeichen, und beschreibt den QR als Datenerfassung für einen SCT. Die Länderreichweite kommt nicht aus einer eigenen Länderregel in EPC069-12, sondern aus dem SCT-Scheme. Dafür ist die [EPC List of SEPA Scheme Countries, EPC409-09 Version 8.0, 24. Dezember 2025](https://www.europeanpaymentscouncil.eu/sites/default/files/kb/file/2025-12/EPC409-09%20EPC%20List%20of%20SEPA%20Scheme%20Countries%20v8.0.pdf) die Quelle.

Der Quellenstand ist bewusst datiert. Neuere Registry- oder EPC-Fassungen sind nicht belegt und dürfen nicht stillschweigend angenommen werden.

## Einheitliche Kernregel

Es gibt genau eine öffentliche fachliche Prüfung mit einem Profilparameter, nicht je Aufrufer eine eigene Regel:

```text
pruefe_iban(roh, profil) -> normalisierte IBAN oder fachlicher Fehler

profil = REGISTRY: Zeichenvorrat, Registry-Länge, MOD 97-10
profil = EPC_SCT: REGISTRY plus Land im versionierten EPC-SCT-Ländersatz
```

`REGISTRY` ist für Stammdaten, sichtbare Zahlungsangaben und ZUGFeRD-IBANID vorgesehen. `EPC_SCT` ist ausschließlich für `build_epc_payload` und damit den Girocode vorgesehen. Das Profil erweitert die Kernregel nur, es dupliziert weder Normalisierung noch Längen- oder Prüfziffernlogik.

Entscheidung: Die länderspezifische Länge wird erzwungen. MOD 97-10 allein ließe etwa eine zu kurze deutsche oder eine beliebige, formal umprüfbare Zeichenfolge zu, obwohl das Registry für jedes registrierte Land eine feste IBAN-Länge festlegt.

Die vorhandene globale Spanne von 15 bis 34 Zeichen entfällt als Gültigkeitsregel. 34 bleibt nur die allgemeine ISO- und EPC-Obergrenze und eine Schutzgrenze vor der tabellarischen Prüfung.

### Normalisierung und Syntax

1. Ein leerer oder nur aus Leerraum bestehender Eingabewert ist für optionale Bankfelder `None`; er ist kein Fehler.
2. Bei einem nichtleeren Wert werden alle Zeichen entfernt, die die vorhandene Python-Normalisierung `roh.split()` als Trennraum entfernt. Damit bleiben die bisher akzeptierten Leerraumvarianten, auch Tabulatoren und Zeilenumbrüche, kompatibel. Danach wird mit `upper()` in Großbuchstaben umgewandelt.
3. Das Ergebnis muss ausschließlich aus ASCII `A` bis `Z` und `0` bis `9` bestehen. Die ersten zwei Zeichen müssen ASCII-Buchstaben, das dritte und vierte Zeichen ASCII-Ziffern sein.
4. Das zweibuchstabige Präfix muss in der Registry-Tabelle stehen. Die Gesamtlänge muss exakt der dort hinterlegten Länge entsprechen.
5. Erst danach wird MOD 97-10 gerechnet. Ein gültiges Ergebnis hat Rest `1`.

Der Prüfer darf keine BBAN-Unterstruktur, Bankleitzahl oder nationale Zusatzprüfungen aus dem Registry nachbilden. Diese sind nicht Gegenstand dieses Auftrags. Die Registry-Länge ist dagegen zwingend. Dadurch bleibt die fachliche Zusage präzise: „strukturell und mit Prüfziffer gültige IBAN nach Registry-Länge“, nicht „existierendes Bankkonto“.

### MOD 97-10, exakt

Für die bereits normalisierte Zeichenfolge `CCDDBBAN` gilt:

1. Stelle die ersten vier Zeichen ans Ende: `BBANCCDD`.
2. Ersetze jeden Buchstaben durch seine zweistellige Zahl `A=10`, `B=11`, ..., `Z=35`. Ziffern bleiben Ziffern. Das Ergebnis ist eine Dezimalziffernfolge.
3. Berechne den Rest dieser Folge modulo 97, ohne sie als eine einzige Ganzzahl zu speichern. Beginne mit `rest = 0`. Für jede Dezimalziffer `d` von links nach rechts setze `rest = (rest * 10 + d) mod 97`.
4. Akzeptiere genau dann, wenn `rest = 1` gilt.

Diese Restrechnung ist mathematisch gleich der Division der gesamten erweiterten Zahl durch 97, braucht aber keine große Ganzzahl.

### Durchgerechnete, erfundene Probe

Die folgende Zeichenfolge ist absichtlich konstruiert und kein Beleg für ein existierendes Konto. Sie trägt das eindeutige Testwort `PROBE` und ausschließlich Nullen im Rest des BBAN:

```text
BBAN für die Konstruktion: PROBE0000000000000000000
Land und vorläufige Prüfziffer: AZ00
Umgestellt: PROBE0000000000000000000AZ00
Buchstabenersatz: 25272411140000000000000000000103500
```

Die stückweise Restrechnung, in Sechsergruppen nur zur Lesbarkeit, lautet:

| angehängte Gruppe | Rest vorher | Rest nachher |
| --- | ---: | ---: |
| 252724 | 0 | 39 |
| 111400 | 39 | 30 |
| 000000 | 30 | 34 |
| 000000 | 34 | 45 |
| 000001 | 45 | 52 |
| 03500 | 52 | 32 |

Für die Erzeugung lautet die Prüfziffer `98 - 32 = 66`. Der erfundene Testwert ist daher:

```text
AZ66PROBE0000000000000000000
```

Die Gegenprobe verschiebt `AZ66` ans Ende und rechnet über dieselbe Ziffernfolge mit `66` statt `00`. Der Rest ist `1`. Die Länge ist 28 und entspricht `AZ` in der untenstehenden Tabelle. Die Probe erfüllt bewusst nicht die nicht implementierte nationale BBAN-Unterstruktur von AZ, was zulässig ist, weil diese Spezifikation nur Präfix, Länge und MOD 97-10 fordert.

## Länder und Längen

Die Tabelle ist eine Abschrift der Spalte `IBAN length` des oben genannten SWIFT Registry Release 103. Sie enthält alle 89 dort registrierten Präfixe, einschließlich `XK`, das nicht in der vorhandenen ISO-Länderliste stehen muss.

| Präfix | Länge | Präfix | Länge | Präfix | Länge |
| --- | ---: | --- | ---: | --- | ---: |
| AD | 24 | AE | 23 | AL | 28 |
| AT | 20 | AZ | 28 | BA | 20 |
| BE | 16 | BG | 22 | BH | 22 |
| BI | 27 | BR | 29 | BY | 28 |
| CH | 21 | CR | 22 | CY | 28 |
| CZ | 24 | DE | 22 | DJ | 27 |
| DK | 18 | DO | 28 | EE | 20 |
| EG | 29 | ES | 24 | FI | 18 |
| FK | 18 | FO | 18 | FR | 27 |
| GB | 22 | GE | 22 | GI | 23 |
| GL | 18 | GR | 27 | GT | 28 |
| HN | 28 | HR | 21 | HU | 28 |
| IE | 22 | IL | 23 | IQ | 23 |
| IS | 26 | IT | 27 | JO | 30 |
| KW | 30 | KZ | 20 | LB | 28 |
| LC | 32 | LI | 21 | LT | 20 |
| LU | 20 | LV | 21 | LY | 25 |
| MC | 27 | MD | 24 | ME | 22 |
| MK | 19 | MN | 20 | MR | 27 |
| MT | 31 | MU | 30 | NI | 28 |
| NL | 18 | NO | 15 | OM | 23 |
| PK | 24 | PL | 28 | PS | 29 |
| PT | 25 | QA | 29 | RO | 24 |
| RS | 22 | RU | 33 | SA | 24 |
| SC | 31 | SD | 18 | SE | 24 |
| SI | 19 | SK | 24 | SM | 27 |
| SO | 23 | ST | 25 | SV | 28 |
| TL | 23 | TN | 24 | TR | 26 |
| UA | 29 | VA | 22 | VG | 24 |
| XK | 20 | YE | 30 |  |  |

### Pflege und Generierung

Die Tabelle soll als generiertes, eingechecktes Datenmodul im Code liegen, beispielsweise nur als unveränderliche Zuordnung `Präfix -> Länge` und als hiervon abgeleiteter EPC-Satz. Die Laufzeit lädt weder PDF noch Netzressource.

Die Bauart von `backend/scripts/gen_laender_iso.py` passt: ein Wartungsskript erzeugt deterministisch den Modulblock, und `--pruefen` erzeugt erneut und schlägt bei Abweichung gegen den eingecheckten Block fehl. Das schützt vor Handänderungen und ist im CI ohne Netz ausführbar.

Anders als bei `gen_laender_iso.py` darf der Generator nicht versuchen, bei jedem `--pruefen` eine aktuelle SWIFT-Fassung aus dem Netz zu laden. Das wäre nicht deterministisch und das Registry ist als PDF ein ungeeignetes Vertragsformat. Stattdessen wird die bei einer bewussten Aktualisierung bezogene SWIFT-TXT-Fassung als Eingabeartefakt mit Release, Ausgabemonat, Original-URL und SHA-256 im Repository abgelegt. Der Generator liest ausschließlich dieses Artefakt, prüft die erwarteten 89 Einträge und schreibt auf stdout. Ein separater, dokumentierter Wartungsschritt beschafft eine neue Fassung, prüft deren Herkunft und aktualisiert Artefakt, Generatorergebnis und Quellenstand gemeinsam.

Für den `EPC_SCT`-Satz gilt dieselbe Regel mit einem separaten versionierten Eingabeartefakt aus EPC409-09. Der Satz darf nicht aus `LAENDER` mit 47 Einträgen und auch nicht aus `ISO_LAENDER` mit 249 Einträgen abgeleitet werden: beide Listen sind Formularlisten mit anderer Semantik und anderem Umfang.

## Nicht registrierte Länder und Bestandsdaten

### Neue Eingaben

Für eine nichtleere neue Eingabe mit Präfix außerhalb der Registry ist die Entscheidung klar: `REGISTRY` lehnt sie ab. Eine Zeichenfolge für ein Land ohne registriertes IBAN-System ist keine IBAN; nur MOD 97-10 zu fordern würde eine frei erfundene Landesregel akzeptieren. Ein Kunde in einem solchen Land kann das optionale Feld `bank_iban` leer lassen. Das Programm kann weiterhin Rechnungen in allen 47 kuratierten Kundenländern erstellen, weil `bank_iban` nicht Pflicht ist.

### Bereits gespeicherte Werte

Die Fachentscheidung, wie streng Bestandsdaten behandelt werden, gehört dem Produktverantwortlichen. Es gibt drei Optionen:

| Option | Verhalten bei vorhandener, nun ungültiger IBAN | Folge |
| --- | --- | --- |
| A: Sperren | Rechnungserzeugung bricht mit konkreter Korrekturmeldung ab. | Höchste Sicherheit, kann die Erstellung von Rechnungen blockieren. |
| B: Weglassen mit Warnung | Neue Ausgabe enthält weder sichtbare IBAN noch `ram:IBANID` noch Girocode; der Vorgang warnt. | Rechnung bleibt möglich, Zahlungsangaben fehlen aber bewusst. |
| C: Übergangsbestand | Ungültige Altwerte bleiben bis zu einem festgelegten Stichtag ausgabefähig. | Kleinster unmittelbarer Bruch, löst Issue #91 für diesen Bestand nicht vollständig. |

Hier wird keine dieser Optionen entschieden. Vor der Implementierung ist A, B oder C verbindlich festzulegen. Unabhängig davon gilt:

1. Eine Migration verändert oder löscht keine gespeicherten IBANs automatisch. Bereits gestellte, unveränderliche Belege bleiben unverändert.
2. Beim bloßen Öffnen eines Kunden- oder Einstellungsformulars wird ein Altwert nicht zurückgewiesen und nicht umgeschrieben. Er wird als vorhandener Wert angezeigt.
3. Beim nächsten Speichern eines Kundenformulars muss ein nichtleerer Altwert die neue `REGISTRY`-Prüfung bestehen, sonst bleibt das Formular mit Feldfehler stehen. Das trifft heute Kunden, weil sie bereits über `bankverbindung.pruefe_iban` laufen.
4. Einrichtung und Einstellungen müssen dieselbe Prüfung vor dem Persistieren erhalten. Heute speichern beide Leerzeichen-entfernt und großgeschrieben ohne IBAN-Prüfung. Dort fällt ein Altwert also beim nächsten Speichern der Firmendaten auf.
5. Bei einer Rechnungserzeugung fällt der Wert an drei Stellen auf: sichtbarer PDF-Zahlungshinweis, ZUGFeRD-`ram:IBANID` und EPC-Girocode. Das gewählte Verhalten A, B oder C muss für alle drei Stellen konsistent umgesetzt werden, damit kein ungültiger Wert nur in XML oder nur als Klartext weitergegeben wird.

Die Produktentscheidung muss zudem festlegen, ob beim Speichern anderer Felder ein unveränderter Altwert mitgeprüft werden soll. Die oben beschriebene konservative Regel tut dies. Eine Alternative „nur geändertes IBAN-Feld prüfen“ reduziert Regressionsdruck, lässt aber den Altwert dauerhaft fortleben; sie ist nicht ohne ausdrückliche Entscheidung zulässig.

## EPC-Girocode und unterschiedliche Strenge

`build_epc_payload` ruft heute `_normalize_iban` auf. Es schreibt danach die normalisierte IBAN in Zeile 7 des Payloads. Es hat keine Länderliste und die bisherige Regex akzeptiert jeden Präfix mit 15 bis 34 alphanumerischen Zeichen. Eine strengere `REGISTRY`-Prüfung ändert deshalb das aktuelle Verhalten unmittelbar: falsche Prüfziffern, falsche Landeslängen und unbekannte Präfixe erreichen den Payload nicht mehr.

Der PDF-Aufrufer stellt den Klartext `IBAN: ...` jedoch vor dem `try` zusammen. `ValueError` beim QR-Aufbau unterdrückt danach nur QR-Bild und Scan-Hinweis. Die XML-Funktion übernimmt ihre IBAN aktuell ungeprüft. Eine allein im QR-Aufbau verschärfte Prüfung genügt daher nicht für Issue #91.

EPC069-12 selbst führt keine eigene Liste erlaubter Präfixe, fordert aber eine IBAN für den SCT. Deshalb gilt:

1. Stammdaten verwenden `REGISTRY`. Eine registrierte, nicht zu SEPA gehörende IBAN kann als Bankangabe gespeichert werden, wenn der Produktentscheid zum Bestandsverhalten sie ausgeben lässt.
2. `build_epc_payload` verwendet `EPC_SCT`. Zusätzlich zur Registry-Prüfung muss der Präfix im aus EPC409-09 generierten SCT-Ländersatz stehen. Damit kann ein gültiger, aber nicht SCT-tauglicher Registry-Wert keinen falschen Girocode erzeugen.
3. PDF und ZUGFeRD verwenden nicht automatisch `EPC_SCT`, sondern mindestens `REGISTRY`; die Frage, ob Zahlungsart `58` für einen nicht-SEPA-Wert fachlich zulässig ist, ist für diese Spezifikation nicht belegt und muss bei gewünschter Verschärfung separat gegen die ZUGFeRD/EN-16931-Regel belegt werden.

So sind zwei Strengegrade möglich, aber die Regel existiert nur einmal: erst Kernnormalisierung, Tabellenlänge und Prüfziffer, dann optional der zusätzliche EPC-Satz.

## Datenwache in POSIX-Shell und awk

### Machbarkeit und Verfahren

MOD 97-10 ist in POSIX-Shell mit POSIX-`awk` zuverlässig berechenbar. `awk` ist auf macOS und den Debian-CI-Abbildern vorhanden; `bc` wird nicht vorausgesetzt. Die IBAN darf nie als Shell- oder awk-Ganzzahl umgewandelt werden.

Die awk-Funktion arbeitet Zeichen für Zeichen:

```text
rest = 0
für jedes Zeichen von BBANCCDD:
  falls Ziffer: führe genau diese Ziffer zu
  falls Buchstabe: ersetze A..Z durch 10..35 und führe beide Dezimalziffern nacheinander zu
für jede zugeführte Dezimalziffer d:
  rest = (rest * 10 + d) % 97
gültig genau bei rest == 1
```

Weil `rest` stets zwischen 0 und 96 liegt, ist der größte Zwischenwert vor `% 97` nur 969. Das ist in jeder üblichen awk-Zahlendarstellung exakt; die Länge der ursprünglichen IBAN spielt keine Rolle.

### Erkennung und Ausnahme

Der Hook verarbeitet weiterhin nur neu hinzugekommene Diff-Zeilen. Er übergibt jede Zeile an genau einen awk-Lauf mit der generierten Längentabelle. Der awk-Lauf muss:

1. Kandidaten nur an Nicht-Alphanumerisch-Grenzen erkennen, damit kein Teil eines längeren Tokens genügt.
2. Zwei ASCII-Buchstaben, zwei Ziffern und die nach der Tabelle erwartete Zahl alphanumerischer BBAN-Zeichen zulassen; zwischen Zeichen dürfen ASCII-Leerzeichen oder Tabulatoren stehen. Der Kandidat wird vor Länge und Prüfziffer von diesen Trennzeichen befreit und in ASCII-Großschreibung gebracht.
3. Unbekannte Länder, falsche Länge und MOD-97-Rest ungleich 1 nicht als IBAN-Befund melden. Sie sind keine hinreichend starke Evidenz für eine echte IBAN.
4. Jeden erfolgreichen Kandidaten melden, außer er ist die Testfixture-Form: BBAN beginnt mit dem Literal `PROBE` und besteht danach ausschließlich aus `0`; auch dann muss Länge und MOD 97-10 stimmen.

Die Ausnahme ist absichtlich enger als „enthält Probe“ und prüft weiterhin die Prüfziffer. Sie unterstützt genau konstruierte Fixtures wie `AZ66PROBE0000000000000000000`. Sie ist keine Behauptung, dass ein so geformtes Konto unmöglich echt sein kann. Falls diese kleine Restlücke für die Datenwache nicht akzeptabel ist, bleibt als sichere Alternative die Ausnahme ganz weg und Testdaten werden nur über den vorhandenen Override oder außerhalb gepushter Zeilen erzeugt. Diese Produktentscheidung ist nicht erforderlich, um MOD 97-10 im Hook zuverlässig zu rechnen.

Das awk-Programm erhält die Längentabelle aus einer eingecheckten, shell-lesbaren generierten Datei oder einer vom selben Generator erzeugten awk-Zuordnung. Python, `bc`, GNU-spezifisches `grep -P` und `grep -o` sind nicht erlaubt. Die vorhandene Datenwache verwendet bereits `grep -oE`, das kein POSIX-Versprechen ist; die neue IBAN-Prüfung darf sich darauf nicht stützen.

### Wahrscheinlichkeitsrechnung

Für eine feste Folge aus Land, BBAN und allen übrigen nicht als Prüfziffer gewählten Stellen bestimmt MOD 97-10 genau eine der 100 möglichen zweistelligen Prüfziffern `00` bis `99`. Bei einer gleichverteilten willkürlich erfundenen Ziffernfolge sind die zwei Prüfziffern daher mit Wahrscheinlichkeit

```text
1 / 100 = 0,01 = 1 %
```

richtig. Beispiel: Werden 10.000 unabhängige passende, ansonsten zufällige Kandidaten erfunden, bestehen im Erwartungswert `10.000 * 1/100 = 100` die Prüfziffer und `9.900` nicht. Die Prüfziffer senkt damit Fehlalarme aus zufälligen Zeichenfolgen ungefähr um Faktor 100 gegenüber einer reinen Formatwache. Sie lässt aber ungefähr einen von 100 zufällig gebauten, formatpassenden Kandidaten durch und ist keine Echtheitsprüfung. Landeslänge und bekannte Präfixe senken die praktische Zufallsrate zusätzlich, ohne dass hierfür aus den vorhandenen Fakten eine belastbare Gesamtwahrscheinlichkeit ableitbar ist.

## Abnahmekriterien

Die Umsetzung beginnt test-first. Jedes Kriterium benennt die Mutation, die seinen Test rot machen muss.

### Anwendung

| Kriterium | Ausführbarer Nachweis | Rote Mutation im Produktivcode |
| --- | --- | --- |
| Normalisierung | Eine gemischt geschriebene, mit Leerraum getrennte, konstruierte gültige Probe wird als großgeschriebene Zeichenfolge ohne Trennraum gespeichert. | Das Entfernen von Leerraum oder `upper()` entfernen. |
| Prüfziffer | Die erfundene `AZ66PROBE0000000000000000000` wird im `REGISTRY`-Profil angenommen; dieselbe Zeichenfolge mit einer um eins veränderten Prüfziffer wird abgelehnt. | Den Vergleich `rest == 1` entfernen oder auf `rest == 0` ändern. |
| Landeslänge | Ein Wert mit gültiger MOD-97-Prüfziffer, aber um ein Zeichen falscher AZ-Länge, wird abgelehnt. | Den Längenvergleich gegen die Registry-Tabelle entfernen. |
| Unbekanntes Präfix | Ein syntaktisch passender, MOD-97-konstruierter Wert mit nicht registriertem Präfix wird abgelehnt. | Die Prüfung auf Mitgliedschaft in der Registry-Tabelle entfernen. |
| Kundenformular | POST auf Kunden anlegen und bearbeiten nimmt eine gültige Probe an, weist eine fehlerhafte zurück, behält bei Fehler die eingegebenen Bankfelder und persistiert nichts Teilweises. | In `_bank_felder` den Aufruf von `pruefe_iban` entfernen. |
| Einstellungen | POST auf `/settings/firma` nimmt keine nichtleere falsche Prüfziffer an und verändert die bestehende Firmenzeile nicht. | Die neue IBAN-Prüfung vor den Feldzuweisungen entfernen. |
| Einrichtung | POST auf `/setup` mit nichtleerer falscher IBAN liefert Formularfehler und setzt `setup_completed_at` nicht. | Die neue Prüfung im Setup-Handler entfernen. |
| Gemeinsame Regel | Kunden, Einstellungen und Einrichtung liefern für dieselbe ungültige Eingabe dieselbe fachliche IBAN-Fehlermeldung. | Einen der drei Wege wieder durch eigene Regex-Logik ersetzen. |
| EPC-Profil | Eine registry-gültige Probe mit Präfix außerhalb des generierten SCT-Satzes darf nicht zum EPC-Payload führen; eine gleichartig gültige SCT-Probe führt zu einem Payload mit normalisierter IBAN in Zeile 7. | Den EPC-Satztest in `build_epc_payload` entfernen. |
| Kein Teil-Output | Für eine nach dem gewählten Bestandsverhalten A, B oder C ungültige gespeicherte IBAN entspricht PDF-Klartext, XML-`ram:IBANID` und QR exakt diesem Verhalten, niemals nur teilweise. | Die Validierung nur vor QR-Aufbau einfügen und Klartext/XML unverändert lassen. |
| Generator-Drift | Der IBAN-Generator liefert mit `--pruefen` für die eingecheckte Quelle Erfolg und scheitert nach einer absichtlichen Änderung einer generierten Ländergröße. | Den Vergleich zwischen Generatorausgabe und Datenmodul entfernen. |

Das Kriterium „Kein Teil-Output“ wird erst geschrieben, wenn A, B oder C entschieden ist. Seine Testdaten verwenden eine künstliche, nach früherer Regex zulässige, aber nach neuer Regel ungültige Zeichenfolge und keine echte IBAN.

### Hook

| Kriterium | Ausführbarer Nachweis | Rote Mutation im Hook |
| --- | --- | --- |
| Länderübergreifend | Ein Wegwerf-Repository mit einer neu hinzugefügten Zeile, die die gültige AZ-Probe enthält, lässt den Hook mit Exit 1 und Klasse `IBAN-Format` enden. | Die Kandidatenerkennung auf `DE` festsetzen. |
| Prüfziffer reduziert Befund | Dieselbe Form mit um eins veränderter Prüfziffer lässt den Hook mit Exit 0 enden. | Die awk-MOD-97-Prüfung aus dem Befundpfad entfernen. |
| Trennraum | Die gültige Probe, in Gruppen mit einzelnen Leerzeichen und Tabulatoren dargestellt, wird ebenfalls gefunden. | Die Leerraum-Normalisierung im awk-Teil entfernen. |
| Falsche Landeslänge | Ein Kandidat mit bekanntem Präfix, korrekter Prüfziffer für seine Zeichenfolge, aber falscher Registry-Länge führt nicht zu `IBAN-Format`. | Die Längenprüfung entfernen. |
| Konstruierte Ausnahme | Genau die gültige Form `AZ66PROBE` plus 19 Nullen lässt den Hook mit Exit 0 enden. | Die vollständige Fixture-Prädikatsprüfung entfernen. |
| Keine breite Ausnahme | Ein gültiger Kandidat, der `PROBE` enthält, aber danach ein Nichtnullzeichen hat, lässt den Hook mit Exit 1 enden. | Die Ausnahme auf „enthält PROBE“ verkürzen. |
| POSIX-Portabilität | Der Hook-Test läuft mit `/bin/sh` und `awk`; er setzt weder Python noch `bc` voraus und benutzt in der neuen IBAN-Strecke kein `grep -P` oder `grep -o`. | Den awk-Aufruf durch `bc` oder `python` ersetzen. |

Die Hook-Charakterisierungstests sollen wie die vorhandene `.githooks/test_datenwache.sh` Wegwerf-Repositories verwenden und den Exit-Code ohne Pipeline abgreifen.

## Testdatenregel

Echte IBANs gehören weder in Tests, Fixtures, Dokumentation noch Issues. Bestehende Literale werden durch konstruktive Proben ersetzt, bevor die neue Erkennung sie als Befund behandeln kann. Das ist ein notwendiger Bereinigungsumfang der späteren Umsetzung, aber keine Änderung dieser Spezifikation.

Eine gültige künstliche Probe entsteht umkehrbar:

1. Wähle ein Registry-Präfix und eine BBAN-Zeichenfolge der erforderlichen Länge. Verwende einen klaren Sentinel wie `PROBE` und danach Nullen, soweit die getestete Regel keine BBAN-Unterstruktur erzwingt.
2. Hänge `CC00` an die BBAN an, ersetze Buchstaben mit `A=10` bis `Z=35` und berechne den stückweisen Rest `r` modulo 97.
3. Setze die zwei Prüfziffern auf `98 - r`, immer zweistellig. Bei `r = 0` entsteht `98`; ein Sonderfall ist nicht nötig, weil die hier verwendete Konstruktion in der zulässigen IBAN-Domäne liegt.
4. Bilde `CC` plus diese Prüfziffer plus BBAN. Die Gegenrechnung über BBAN plus vollständige erste vier Zeichen muss Rest 1 liefern.

Die oben vollständig gerechnete AZ-Probe ist die Referenz für diesen Prozess. In Testquelltext werden Literale zusätzlich in harmlose Teile zusammengesetzt und die Namen enthalten `probe`, damit die Datenwache ihre Absicht erkennen kann. Die Ausnahme des Hooks wird nur für die eng beschriebene komplette Fixture-Form verwendet, nicht für allgemeine Testnamen.

## Nicht ausgeführt und nicht geprüft

Es wurden keine Produktivcode-, Hook- oder Teständerungen vorgenommen. Es wurden keine Container, keine Anwendungssuite, kein Hook-Test und kein Generatorlauf ausgeführt. Nicht belegt und daher nicht entschieden ist die fachliche Zulässigkeit eines nicht-SEPA-IBAN-Präfixes in ZUGFeRD-Zahlungsart 58. Vor einer Erweiterung von `REGISTRY` auf `EPC_SCT` für XML muss dies gegen die einschlägige ZUGFeRD- oder EN-16931-Regel nachgewiesen werden.
