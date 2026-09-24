# Spezifikation: VATEX-Codes (BT-121) in Abgehakt

Stand der Bestandsaufnahme: 2026-09-24 (Repo-Stand dieses Arbeitsbaums).
Gegenstand: fachliche Vorgabe fuer Issues #94 und #95 (aus PR #87). Kein
Umsetzungsauftrag in diesem Dokument: Produktivcode und Tests aendert jemand
anderes gegen diese Spec, test-first.

**Kein Steuerrat.** Normverweise sind Recherche mit Primaerquellen, keine
Auskunft eines Steuerberaters.

## Was diese Spec nicht getan hat

- Die pytest-Suite wurde **nicht** ausgefuehrt (Auftrag: nur im Container, hier
  bewusst unterlassen).
- Mustang-CLI wurde **nicht** gegen Beispiel-XML mit falschem oder richtigem
  VATEX-Code aufgerufen. Aussagen dazu stehen als "nicht belegt" oder als
  Ableitung aus Schematron-Quellen.
- Die Excel-/Spreadsheet-Fassung der CEF-VATEX-Liste auf dem Digital-Building-
  Blocks-Portal wurde nicht heruntergeladen (Seitenabruf timeout). Stattdessen
  die veroeffentlichte Peppol-Spiegelung der Codeliste und die CEN-Artefakte.

## Bestand im Repo (Tatsache)

### Erzeugbare Kategorien

`validator.VALID_TAX_CATEGORIES` = `{S, AE, K, O, E}`.

Kategorie **Z** entsteht nicht als Belegfeld, sondern in `_item_tax_category`:
bei Belegkategorie `S` und Positionssteuersatz `0` wird `Z` geschrieben
(`zugferd_xml.py`).

`EXEMPTION_REASONS` deckt nur `AE`, `E`, `K`, `O` ab. `S` und abgeleitetes `Z`
haben keinen Freitext.

### Generator heute (`_tax_summaries_xml` / `_line_items_xml`)

| Ebene | Element | Wann |
|---|---|---|
| Beleg, BG-23 (`ApplicableHeaderTradeSettlement` / `ApplicableTradeTax`) | BT-120 `ExemptionReason` | wenn `inv_cat in EXEMPTION_REASONS` |
| Beleg, BG-23 | BT-121 `ExemptionReasonCode` | **nur** wenn `inv_cat == "AE"`, Wert fest `VATEX-EU-AE` |
| Position, BT-151/BT-152 (`IncludedSupplyChainTradeLineItem` / `ApplicableTradeTax`) | BT-120 `ExemptionReason` | wie Beleg, gleicher Freitext |
| Position | BT-121 | **nie** (Kommentar im Code: BT-121 nur Belegebene) |

Fundstelle Code: `backend/app/services/zugferd_xml.py`, Block um Zeilen 138 bis 171
(Beleg) und 97 bis 135 (Position); Schranke `if inv_cat == "AE"` bei 157 bis 161.
Kommentar dort: VATEX fuer K/E/O sei nicht Teil dieses Auftrags.

CII-Sequenz auf Belegebene (bestehender Schema-Test): `ExemptionReason` vor
`CategoryCode`, dann `ExemptionReasonCode`, dann `RateApplicablePercent`
(`test_zugferd_xml_schema.py`, `test_ae_exemption_reason_code_steht_nach_category_code`).

### Validator heute

`backend/app/services/validator.py` kennt **kein** VATEX, kein BT-120 und kein
BT-121. Er erzwingt unter anderem:

- gueltige Kategorie aus `VALID_TAX_CATEGORIES`;
- Steuersatz 0 und Steuerbetrag 0 bei AE/K (und rate 0 bei O/E in
  `STEUERFREIE_KATEGORIEN`);
- Verkaeufer- und Kaeufer-USt-IdNr. bei AE und K;
- Lieferdatum bei K unabhaengig vom Kleinbetrag (BR-IC-11 als
  Anwendungsbegruendung im Kommentar).

Ein falscher oder fehlender `ExemptionReasonCode` laesst den lokalen Pruefer
also unberuehrt.

### Wissensdatei #94

`knowledge/ZUGFeRD/reverse-charge-pflichtangaben.md` Zeile 108 behauptet noch:
"BT-121 wird nicht gesetzt." Das widerspricht dem Generator seit dem AE-Code.
Ersatztext steht unten in Abschnitt 4; die Datei selbst wird hier **nicht**
geaendert.

---

## 1. Welcher VATEX-Code zu welcher Kategorie

Codeliste: **CEF VATEX** (Agency CEF), Spiegelung in Peppol BIS Billing 3.0
Codelist `vatex`, Abruf 2026-09-24:
https://docs.peppol.eu/poacc/billing/3.0/codelist/vatex/

Steuerkategorien (UNTDID 5305 / UNCL5305):
https://docs.peppol.eu/poacc/billing/3.0/codelist/UNCL5305/

| Kategorie im Generator | Sachlich richtiger BT-121 | Rechtsgrundlage (Kurz) | Quelle |
|---|---|---|---|
| **S** (Standard) | **keiner** | Keine Befreiung; BT-120/BT-121 gehoeren nicht zur Standardbesteuerung | EN 16931: Regeln BR-*-10 greifen nicht auf `S` |
| **Z** (Zero rated, aus S+0%) | **keiner**; BT-120 und BT-121 sind **verboten** | Nullsatz, steuerbar | BR-Z-10 (Peppol/CEN-Spiegel): `not((ExemptionReason) or (ExemptionReasonCode))`. https://docs.peppol.eu/poacc/billing/3.0/upcoming/rules/ubl-tc434/BR-Z-10/ |
| **AE** (Reverse charge) | **`VATEX-EU-AE`** | Art. 196 MwStSystRL; Hinweispflicht § 14a Abs. 1 UStG | VATEX-Eintrag: "Only use with VAT category code AE", stuetzt BR-AE-10. https://docs.peppol.eu/poacc/billing/3.0/codelist/vatex/ |
| **K** (innergemeinschaftliche Lieferung) | **`VATEX-EU-IC`** (wenn ein Code gesetzt wird); **`VATEX-EU-AE` ist falsch** | § 4 Nr. 1b i. V. m. § 6a UStG; Art. 138 MwStSystRL | VATEX-Eintrag: "Intra-Community supply", "Only use with VAT category code K", stuetzt BR-IC-10. Dieselbe Codelist-URL. |
| **E** (hier: Kleinunternehmer § 19 UStG) | **keiner**, der § 19 UStG abbildet | BR-E-10 verlangt Text **oder** Code; der Generator erfuellt das mit BT-120 | In der Peppol-VATEX-Liste (Abruf oben) gibt es **keinen** Code fuer deutsches § 19 / Kleinunternehmer. `VATEX-FR-FRANCHISE` ist franzoesisch und fachfremd. EU-Codes `VATEX-EU-D/F/I/J` sind andere Tatbestaende und nur mit E gekoppelt, aber nicht § 19. |
| **O** (Outside scope / nicht steuerbar) | **`VATEX-EU-O`** (wenn ein Code gesetzt wird) | BR-O-10; im Produkt derzeit Freitext zu § 3a Abs. 2 | VATEX: "Not subject to VAT", "Only use with VAT category code O" |

### Lesart zu K und `VATEX-EU-AE`: bestaetigt falsch

Die Annahme, `VATEX-EU-AE` gehoere nicht auf Kategorie K, ist **richtig**.
`VATEX-EU-AE` ist laut Codeliste ausschliesslich fuer AE ("Reverse charge").
Fuer K ist der passende Code `VATEX-EU-IC` ("Intra-Community supply").
Beleg: Peppol VATEX-Codelist (Links oben); zusaetzlich EC Technical Guidance
Document (PDF, Digital Building Blocks), Abschnitt zu Intra-Community supply:
Reason-Code `VATEX-EU-IC`, Kategorie `K`:
https://ec.europa.eu/digital-building-blocks/sites/download/attachments/467108974/eInvoicing%20technical%20guidance%20document_v1.pdf

### Was der Generator heute tut (Ist), getrennt vom Soll der Codeliste

| Kategorie | BT-120 heute | BT-121 heute |
|---|---|---|
| S | keiner | keiner |
| Z | keiner | keiner |
| AE | gesetzt (EXEMPTION_REASONS) | `VATEX-EU-AE` auf BG-23 |
| K | gesetzt | **keiner** (passt zur Schranke; soll-Code waere IC, siehe Entscheidung unten) |
| E | gesetzt | keiner |
| O | gesetzt | keiner |

### Entscheidung dem Menschen vorbehalten: Codes fuer K und O nachziehen?

| Option | Folge |
|---|---|
| A: Ist beibehalten (nur AE hat BT-121) | BR-IC-10 / BR-O-10 bleiben ueber BT-120 erfuellt. Maschinelle Auswertung ohne Freitext schwächer. Kommentar im Code bleibt wahr. |
| B: `VATEX-EU-IC` fuer K und/oder `VATEX-EU-O` fuer O auf BG-23 ergaenzen | Entspricht Gutachten-Empfehlung "beide Felder" und EC-Guidance-Beispiel. Schematron-OR bleibt erfuellt. Neue Tests noetig (Anwesenheit des **richtigen** Codes plus Abwesenheit auf Position). |
| C: E ebenfalls mit irgendeinem VATEX versehen | **Nicht empfohlen** ohne belegten DE-Code; falscher EU-Artikel-Code waere sachlich falsch. |

Diese Spec entscheidet A/B/C **nicht**. Issue #95 verlangt zunaechst die
Absicherungs-Haelfte: K (und analog) darf keinen **falschen** Code tragen,
insbesondere nicht `VATEX-EU-AE`.

---

## 2. BT-121: Pflicht, erlaubt oder verboten

Bezugsebene der BR-*-10-Regeln: **VAT breakdown BG-23** (Belegsteuerblock),
nicht die Positionszeile.

### Nach Kategorie (EN 16931 Schematron, Spiegelung Peppol ubl-tc434)

| Kategorie | BT-120 allein | BT-121 allein | Beide | Keines |
|---|---|---|---|---|
| AE | erlaubt, erfuellt BR-AE-10 | erlaubt, erfuellt BR-AE-10 | erlaubt | verboten (BR-AE-10 fatal) |
| K | erlaubt, erfuellt BR-IC-10 | erlaubt, erfuellt BR-IC-10 | erlaubt | verboten (BR-IC-10 fatal) |
| E | erlaubt, erfuellt BR-E-10 | erlaubt, erfuellt BR-E-10 | erlaubt | verboten (BR-E-10 fatal) |
| O | erlaubt, erfuellt BR-O-10 | erlaubt, erfuellt BR-O-10 | erlaubt | verboten (BR-O-10 fatal) |
| Z | verboten | verboten | verboten | geboten (BR-Z-10) |
| S | nicht Gegenstand dieser BR-*-10 | ebenso | ebenso | normal |

Regeltexte und Testausdruecke (jeweils `exists(BT-120) or exists(BT-121)` bzw.
Negation bei Z):

- BR-AE-10: https://docs.peppol.eu/poacc/billing/3.0/rules/ubl-tc434/BR-AE-10/
- BR-IC-10: https://docs.peppol.eu/poacc/billing/3.0/rules/ubl-tc434/BR-IC-10/
- BR-E-10: https://docs.peppol.eu/poacc/billing/3.0/rules/ubl-tc434/BR-E-10/
- BR-O-10: https://docs.peppol.eu/poacc/billing/3.0/rules/ubl-tc434/BR-O-10/
- BR-Z-10: https://docs.peppol.eu/poacc/billing/3.0/upcoming/rules/ubl-tc434/BR-Z-10/

Die Formulierungen nennen im Fliesstext oft den **gemeinten** Code-Sinn
("meaning Reverse charge" usw.), der Schematron-**Test** prueft aber nur die
Disjunktion Anwesenheit, nicht den konkreten Code-Wert und nicht den
Wortlaut des Freitexts.

### Rangfolge BT-120 gegen BT-121

**Heute weiterhin: keine normative Rangfolge**, die BT-121 dem BT-120 vorzieht.

- Schematron: reine ODER-Verknuepfung.
- CEF/EC Code-lists-Seite: BT-121 "may be used instead of … or to complement"
  BT-120 (optionaler Code, Alternative oder Ergaenzung):
  https://ec.europa.eu/digital-building-blocks/sites/spaces/DIGITAL/pages/467108957/Code+lists
- ConnectingEurope Issue #161 (2019, closed wontfix): eine harte Zuordnung
  "dieser VATEX-Code nur bei dieser Kategorie" wurde als Bemerkung der
  VATEX-Liste / CEF gesehen, **nicht** als EN-16931-Geschaeftsregel im engeren
  Sinne; vorgeschlagene Schematron-Verschaerfung wurde zurueckgenommen:
  https://github.com/ConnectingEurope/eInvoicing-EN16931/issues/161

Die Aussage in der Wissensdatei unter "Nicht belegt" (keine normative Rangfolge
BT-121 vor BT-120) **stimmt weiterhin**. Was es gibt, sind Empfehlungen
(Gutachten: beide setzen; bei Zwang BT-120 fuer die deutsche Hinweispflicht)
und Peppol-Zusatzregeln zu Code↔Kategorie (siehe Abschnitt 3), nicht ein
CEN-Vorrang des Codes.

EC Technical Guidance nutzt Formulierungen wie "VAT exemption reason code shall
be VATEX-EU-IC". Das ist Leitfaden-Sprache fuer den empfohlenen Code, wenn man
einen setzt; es ersetzt die Schematron-Disjunktion nicht. Normativ fuer die
Validierung bleibt BR-IC-10 bzw. BR-AE-10.

---

## 3. Was der Pruefer in diesem Repo daraus macht

Zwei Schichten:

### A. `validate_invoice` (Python)

Greift bei VATEX/BT-121 **nicht**. Weder Anwesenheit noch Abwesenheit noch
Code-Wert werden geprueft. Belegt durch Fehlanzeige in `validator.py`
(Grep auf VATEX / ExemptionReasonCode / BT-121: keine Treffer).

### B. Mustang-CLI (`mustang.validate`, Profil EN16931)

Mustang prueft erzeugte XML/PDF gegen EN-16931-Artefakte (im Repo belegt durch
Schema-Integrationstests in `test_zugferd_xml_schema.py`, die bei AE mit
`VATEX-EU-AE` `is_valid` erwarten).

| Regel | Wuerde bei fehlendem Text **und** Code greifen? | Wuerde falschen Code (z. B. AE-Code auf K) allein ablehnen? |
|---|---|---|
| BR-AE-10 / BR-IC-10 / BR-E-10 / BR-O-10 | ja, wenn BG-23 weder BT-120 noch BT-121 hat | **nein** nach Schematron-Test (nur `exists`); Wortlaut/Code-Wert ungeprueft |
| BR-Z-10 | greift, wenn Z irgendeinen Grund oder Code traegt | n/a |
| BR-CL-22 (Code muss zur CEF-VATEX-Liste gehoeren) | n/a | prueft Listenmitgliedschaft, **nicht** Kategoriepassung (CEN-Codelist-Schematron) |
| Peppol P0105 bis P0111 (Code erzwingt Kategorie) | | **nicht belegt** fuer Mustang: das sind Peppol-Regeln; ob die installierte Mustang-Fassung sie mitlaeuft, wurde hier nicht gemessen |

**Nicht belegt ohne Lauf:** ob Mustang bei `CategoryCode=K` plus
`ExemptionReasonCode=VATEX-EU-AE` (bei vorhandenem Freitext) rot oder gruen
wird. Nach CEN-Schematron-Logik und Issue #161 ist Gruen plausibel; das ist
kein Freibrief, den falschen Code zu setzen.

Folge fuer #95: die Suite muss die **sachliche** Schranke selbst festhalten.
Mustang allein faengt die Mutation `if inv_cat in ("AE", "K")` mit
`VATEX-EU-AE` fuer K voraussichtlich nicht zuverlaessig ab.

---

## 4. Ersatztext fuer die Wissensdatei (#94)

Fertiger Ersatz fuer den Absatz unter "Was das fuer Abgehakt heisst", der heute
faelschlich "BT-121 wird nicht gesetzt" behauptet. Die Datei wird in diesem
Auftrag **nicht** geschrieben; Implementierung der Doku ist ein separater
Schritt.

Vorschlag (ohne Gedankenstriche):

```markdown
Der Text in `EXEMPTION_REASONS["AE"]` (`backend/app/services/zugferd_xml.py`)
entspricht Variante 2 und ist damit gedeckt. Zum Stand der Generator-Logik:

- **Belegebene BG-23** (`ApplicableHeaderTradeSettlement` /
  `ApplicableTradeTax`, Funktion `_tax_summaries_xml`): Bei Kategorie AE setzt
  das Werkzeug BT-120 (`ram:ExemptionReason`) **und** BT-121
  (`ram:ExemptionReasonCode` = `VATEX-EU-AE`). Die Schranke steht bei
  `if inv_cat == "AE"` (ca. Zeile 157). Bei K, E und O steht auf dieser Ebene
  nur BT-120 aus `EXEMPTION_REASONS`; BT-121 bleibt absichtlich leer
  (Kommentar im Code: VATEX fuer K/E/O nicht Teil des bisherigen Auftrags).
  Sachlich passender Code fuer K waere `VATEX-EU-IC`, fuer O `VATEX-EU-O`
  (CEF-VATEX-Liste); `VATEX-EU-AE` gehoert ausschliesslich zu AE.
- **Positionsebene** (`IncludedSupplyChainTradeLineItem` /
  `ApplicableTradeTax`, Funktion `_line_items_xml`): Bei AE/K/E/O nur BT-120
  (gleicher Freitext). BT-121 gehoert nach Modell zu BG-23 und wird auf der
  Position **nicht** geschrieben.
- **S und Z:** kein ExemptionReason und kein ExemptionReasonCode. Bei Z
  verbietet BR-Z-10 beides.
- **Schreibweise** im Freitext: Die Richtlinie und die Codelisten schreiben
  "Reverse charge" gross. Kein Rechtsmangel, ausdruecklich als nicht belegt
  gefuehrt.
```

Der Absatz "Nicht belegt" zur Rangfolge BT-121 vor BT-120 kann stehen bleiben
(siehe Abschnitt 2: weiterhin zutreffend).

---

## 5. Zusicherungen fuer #95 (Tests, Mutationsbeleg)

Zielort: `backend/tests/test_zugferd_xml.py`, Klasse `TestTaxCategories`
(bestehende AE-Haelfte als Muster: `test_ae_exemption_reason_code_vatex_eu_ae_in_tax_summary`,
Zeilen 691 bis 716).

Jede Zusicherung braucht einen benennbaren roten Fall. Ohne roten Fall gehoert
sie nicht hierher.

### 5.1 Pflicht fuer Kategorie K (Kern von #95)

| ID | Zusicherung | Mutation, die rot macht |
|---|---|---|
| K1 | In BG-23 gibt es **kein** `ram:ExemptionReasonCode` (Element fehlt oder XPath `None`) | Schranke von `if inv_cat == "AE"` auf `if inv_cat in ("AE", "K")` erweitern und denselben Literal-Code `VATEX-EU-AE` (oder `VATEX-EU-IC`) fuer K mitschreiben |
| K2 | Im Positionsblock gibt es **kein** `ram:ExemptionReasonCode` | In `_line_items_xml` einen `ExemptionReasonCode` fuer `inv_cat == "K"` (oder fuer alle `EXEMPTION_REASONS`) einfuegen |

K1 ist die fehlende "zweite Haelfte" gegenueber dem AE-Test. K2 spiegelt die
Positions-Haelfte des AE-Tests; ohne K2 bleibt eine Positions-Regression gruen.

Bestehender Test `test_k_category_code_and_exemption_reason` (Anwesenheit
CategoryCode K + Freitext) bleibt; er ersetzt K1/K2 **nicht**.

### 5.2 Kategorie AE (Regression, bereits weitgehend da)

| ID | Zusicherung | Mutation, die rot macht |
|---|---|---|
| AE1 | BG-23: `ExemptionReasonCode` Text genau `VATEX-EU-AE` | Literal aendern oder Block loeschen |
| AE2 | Position: kein `ExemptionReasonCode` | Code-Block auch in `_line_items_xml` fuer AE setzen |

AE1/AE2 entsprechen dem bestehenden Test; bei Umbau nicht abschwächen.

### 5.3 Kategorien E und O: dieselbe Abwesenheits-Haelfte?

**Ja, sinnvoll**, weil dieselbe Schranken-Mutation sie treffen kann:

| ID | Zusicherung | Mutation, die rot macht |
|---|---|---|
| E1 / O1 | BG-23: kein `ExemptionReasonCode` | Schranke auf `if inv_cat in ("AE", "E")` bzw. `("AE", "O")` oder auf alle Keys von `EXEMPTION_REASONS` erweitern und einen Code schreiben |
| E2 / O2 | Position: kein `ExemptionReasonCode` | wie K2 fuer E bzw. O |

Ohne E1/O1 kann `if inv_cat in EXEMPTION_REASONS:` plus ein generischer Code die
Suite gruen lassen, obwohl E/O dann einen sachlich ungeklaerten oder falschen
Code tragen.

### 5.4 Kategorie Z (und S mit positivem Satz)

| ID | Zusicherung | Mutation, die rot macht |
|---|---|---|
| Z1 | Bei abgeleitetem Z: weder `ExemptionReason` noch `ExemptionReasonCode` auf Position (bestehend teilweise: `test_inland_zero_rate_has_no_exemption_reason`) | Exemption-Block auch fuer `tax_cat == "Z"` oeffnen |
| Z2 | Optional schaerfer: dasselbe auf BG-23 fuer den Z-Zusammenfassungsblock | ExemptionReasonCode in `_tax_summaries_xml` ohne AE-Schranke |

Z braucht **keinen** "richtigen VATEX", sondern die BR-Z-10-Abwesenheit. Der
bestehende Test deckt BT-120 auf Position; BT-121-Abwesenheit auf BG-23 bei Z
ist heute implizit (Schranke nur AE + Z nicht in EXEMPTION_REASONS), aber eine
explizite Zusicherung Z2 ist die Mutation gegen "Code immer schreiben".

### 5.5 Was nicht als Zusicherung taugt

- "Mustang sagt valide" allein fuer K ohne Code: bleibt gruen, wenn man den
  falschen AE-Code auf K setzt (Abschnitt 3). Kein Ersatz fuer K1.
- Freitext-Inhalt von K/E/O als alleiniger Schutz gegen BT-121: aendert sich
  bei Code-Mutation nicht.

---

## 6. Offene Rechtsfrage: § 14a Abs. 1 Satz 3 UStG und Kategorie K

Die Wissensdatei und der Validator-Text stuetzen die USt-IdNr.-Pflicht bei AE
(und der Validator auch bei K) auf **§ 14a Abs. 1 Satz 3 UStG**.

Wortlaut (gesetze-im-internet.de, Abruf 2026-09-24,
https://www.gesetze-im-internet.de/ustg_1980/__14a.html ):

- **Abs. 1** betrifft Umsaetze, bei denen im anderen Mitgliedstaat der
  Leistungsempfaenger die Steuer schuldet, insbesondere sonstige Leistungen
  nach § 3a Abs. 2 (das ist der AE-Fall). Satz 3: In dieser Rechnung sind die
  USt-IdNr. des Unternehmers und die des Leistungsempfaengers anzugeben.
- **Abs. 3** betrifft die **innergemeinschaftliche Lieferung**: Satz 2 verlangt
  dort ebenfalls beide USt-IdNr.

**Folge:** § 14a Abs. 1 Satz 3 **traegt fuer K nicht**. Fuer K ist die
einschlaegige Norm **§ 14a Abs. 3 Satz 2 UStG** (gleiche Pflicht, anderer
Absatz). Das ist belegt aus dem Gesetzestext; kein Steuerrat noetig fuer diese
Absatzzuordnung.

Was **offen** bleibt und hier **nicht** entschieden wird:

- Ob der Validator-Fehlertext und die Wissensdatei nur redaktionell auf Abs. 3
  fuer K umgestellt werden, oder ob weitere Hinweispflichten (Freitext
  "innergemeinschaftliche Lieferung" vs. "Steuerschuldnerschaft…") getrennt
  dokumentiert werden sollen.
- Klaeren muesste das: Fachverantwortung Produkt / Steuerberatung vor
  Betriebspruefung; Primaerquelle bleibt der UStG-Text Abs. 1 vs. Abs. 3.

Nicht erfunden und deshalb hier nicht behauptet: irgendeine weitere
Paragraphennummer ausser dem zitierten § 14a.

---

## Vorgaben an die spaetere Umsetzung (Kurz)

1. Doku #94: Wissensabsatz durch Abschnitt 4 ersetzen; Ist-Verhalten AE mit
   Code beschreiben; K/E/O ohne Code und Positionsregel festhalten.
2. Tests #95: mindestens K1 und K2; empfohlen E1/O1 und E2/O2; AE1/AE2 nicht
   abschwächen; optional Z2.
3. Produktivcode: nur aendern, wenn der Mensch Option B (Codes fuer K/O)
   waehlt. Sonst bleibt die Schranke `inv_cat == "AE"`; die neuen Tests halten
   sie fest.
4. Niemals `VATEX-EU-AE` auf K, E, O, S oder Z schreiben.
5. Weiterhin test-first: zuerst rote Abwesenheits-Tests, dann ggf. Code.

## Quellenverzeichnis

- Repo: `backend/app/services/zugferd_xml.py`, `validator.py`,
  `backend/tests/test_zugferd_xml.py`, `test_zugferd_xml_schema.py`,
  `knowledge/ZUGFeRD/reverse-charge-pflichtangaben.md`
- CEF VATEX (Peppol-Spiegel): https://docs.peppol.eu/poacc/billing/3.0/codelist/vatex/
- UNCL5305: https://docs.peppol.eu/poacc/billing/3.0/codelist/UNCL5305/
- BR-AE-10, BR-IC-10, BR-E-10, BR-O-10, BR-Z-10: Peppol ubl-tc434-Regelseiten
  (URLs in Abschnitt 2)
- CEN Issue zur Kategorie↔VATEX-Zuordnung: https://github.com/ConnectingEurope/eInvoicing-EN16931/issues/161
- EC eInvoicing technical guidance PDF (Digital Building Blocks)
- § 14a UStG: https://www.gesetze-im-internet.de/ustg_1980/__14a.html
- EC Code lists Uebersichtsseite (BT-121 optional / instead or complement):
  https://ec.europa.eu/digital-building-blocks/sites/spaces/DIGITAL/pages/467108957/Code+lists
