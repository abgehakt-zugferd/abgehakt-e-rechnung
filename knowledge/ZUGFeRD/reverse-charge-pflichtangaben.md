# Reverse Charge: Pflichtangaben auf der Ausgangsrechnung

Stand: 2026-09-24 | Quelle: Deep-Research-Gutachten (`Reverse Charge Pflichtangaben
E-Rechnung.docx`), gegengelesen gegen den Code von Abgehakt

**Kein Steuerrat.** Was hier steht, ist eine Recherche mit Primaerquellen, keine
Auskunft eines Steuerberaters. Die tragende Fundstelle fuer die englische
Formulierung ist neu (BMF-Schreiben vom 17.09.2025) und gehoert vor einer
Betriebspruefung bestaetigt, nicht geglaubt.

---

## Der Fall, um den es geht

Deutsche GmbH stellt einem Unternehmen im EU-Ausland eine **sonstige Leistung**
in Rechnung, etwa eine Schulung. Der Leistungsort liegt nach § 3a Abs. 2 UStG
beim Empfaenger, die Steuerschuld geht auf ihn ueber. Im Werkzeug ist das die
Steuerkategorie **AE**.

Abzugrenzen davon:

| Fall | Kategorie | Warum |
|---|---|---|
| Sonstige Leistung an EU-Unternehmer | `AE` | Art. 196 MwStSystRL, Leistungsort beim Empfaenger |
| Warenlieferung in die EU | `K` | Innergemeinschaftliche Lieferung, anderer Tatbestand |
| Drittland | `O` | Nicht steuerbar |

---

## Pflichtangaben

| Angabe | Pflicht oder ueblich | Norm |
|---|---|---|
| Hinweis "Steuerschuldnerschaft des Leistungsempfaengers" | **Pflicht** | § 14a Abs. 1 Satz 1 UStG, Art. 226 Nr. 11a MwStSystRL |
| Englische Fassung "Reverse charge" | Pflicht erfuellend, als Alternative anerkannt | Abschn. 14a.1 Abs. 6 Satz 2 UStAE i. V. m. Anlage 8 zum UStAE |
| Eigene USt-IdNr. | **Pflicht** | § 14a Abs. 1 Satz 3 UStG, § 14 Abs. 4 Satz 1 Nr. 2 UStG |
| USt-IdNr. des Empfaengers | **Pflicht** | § 14a Abs. 1 Satz 3 UStG, Art. 226 Nr. 4 MwStSystRL |
| Kein Steuerausweis im Dokument | **Pflicht** | Steuer entsteht im Ausland |
| Steuersatz und Steuerbetrag im XML mit Wert 0 | **Pflicht** (technisch) | EN 16931, Regeln zur Kategorie AE |
| Nennung von Art. 196 MwStSystRL | nur ueblich | Seit Richtlinie 2010/45/EU nicht mehr gefordert |

---

## Warum § 13b UStG hier falsch waere

Das ist der Kern, und er ist leicht zu verwechseln.

**§ 13b UStG regelt den Eingangsfall:** ein im Inland steuerbarer Umsatz, fuer
den der deutsche Leistungsempfaenger die Steuer gegenueber dem deutschen
Finanzamt schuldet.

Auf der eigenen Ausgangsrechnung an den EU-Kunden liegt der Leistungsort aber im
Ausland. Der Umsatz ist nach § 1 Abs. 1 Nr. 1 UStG im Inland **nicht steuerbar**.
Ein Verweis auf § 13b wuerde eine Steuerschuld nach deutschem Recht behaupten,
die es nicht gibt; die Schuld entsteht nach dem Recht des Empfaengerlandes.

Welches Rechnungsrecht gilt, sagt Art. 219a Abs. 2 Buchst. a MwStSystRL: das des
Mitgliedstaats, in dem der Leistende ansaessig ist. Die Pflichtangabe richtet
sich also nach § 14a Abs. 1 UStG, ohne dass § 13b ueberhaupt greift.

---

## Formulierungen

Drei belegte Varianten, alle zulaessig:

1. **"Steuerschuldnerschaft des Leistungsempfängers / Reverse charge"**
   Der empfohlene Standard. Pflichtteil plus anerkannte englische Fassung, ohne
   ueberfluessigen Richtlinienverweis.
2. **"Steuerschuldnerschaft des Leistungsempfängers / Reverse charge (Art. 196, Directive 2006/112/EC)"**
   Wie oben, mit deklaratorischem Richtlinienbezug. Rechtlich unschaedlich.
3. **"Steuerschuldnerschaft des Leistungsempfängers"**
   Das gesetzliche Minimum. Fuer den Auslandsverkehr unzweckmaessig, weil der
   Empfaenger den Begriff nicht zuordnet.

Der Pflichtteil ist in allen drei Varianten derselbe deutsche Satz. Alles
dahinter ist Zweckmaessigkeit, nicht Recht.

---

## BT-120 gegen BT-121 in der E-Rechnung

EN 16931 kennt fuer die Kategorie AE zwei Felder:

| | BT-120 | BT-121 |
|---|---|---|
| Inhalt | Freitext | Code aus der Codeliste VATEX |
| Wert hier | der Hinweistext | `VATEX-EU-AE` |
| CII-Element | `ram:ExemptionReason` | `ram:ExemptionReasonCode` |

**Regel BR-AE-10 verlangt Text ODER Code**, eine Disjunktion. Die Validierung
scheitert nur, wenn beide fehlen. Die Pruefwerkzeuge testen dabei lediglich, ob
BT-120 vorhanden und nicht leer ist; auf den Wortlaut prueft keine Schematron-Regel.
Die sprachliche Konformitaet nach § 14a Abs. 1 UStG bleibt der Betriebspruefung.

**Empfehlung des Gutachtens: beide Felder setzen.** Der Code macht den Beleg fuer
auslaendische Systeme maschinell verarbeitbar, der Text erfuellt die deutsche
Hinweispflicht auch bei reiner Sichtpruefung. Muss man sich entscheiden, hat
BT-120 Vorrang.

---

## Was das fuer Abgehakt heisst

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

---

## Nicht belegt

Diese Punkte hat die Recherche ausdruecklich offengelassen:

- Eine Pflicht zur Gross- oder Kleinschreibung von "Reverse charge" gibt es
  nicht. Die Grossschreibung folgt der Typografie der Richtlinie.
- Eine normative Rangfolge, nach der BT-121 dem BT-120 vorzuziehen waere,
  existiert nicht. Die Bevorzugung des Codes ist ein Postulat von
  Softwareanbietern, kein Standardisierungsbeschluss.
- Kein Pruefwerkzeug vergleicht den Wortlaut in BT-120 buchstabengetreu.

---

## Quellen

- UStG, Fassung 2025/2026: § 1 Abs. 1 Nr. 1, § 3a Abs. 2, § 13b, § 14 Abs. 4,
  § 14a Abs. 1. https://www.gesetze-im-internet.de/ustg_1980/
- UStAE, konsolidiert; **BMF-Schreiben vom 17.09.2025**, III C 2 - S
  7290/00003/003/013, BStBl I S. 1637: Neufassung Abschn. 14.5 Abs. 24 Satz 2 und
  Abschn. 14a.1 Abs. 6 Satz 2, Einfuehrung der Anlage 8 zum UStAE.
- MwStSystRL 2006/112/EG: Art. 44, 196, 219a, 222, 226 Nr. 4 und Nr. 11a.
- DIN EN 16931-1:2017+A1:2019/AC:2020; CEN/TC 434 Schematron, Regel BR-AE-10.
- Verohallinto (Finnland), VH/2584/03.04.01/2021: "Reverse charge" wird
  anerkannt; keine gesonderten finnischen Textauflagen.

Das vollstaendige Gutachten mit Zitaten im Wortlaut liegt als
`Reverse Charge Pflichtangaben E-Rechnung.docx` daneben.
