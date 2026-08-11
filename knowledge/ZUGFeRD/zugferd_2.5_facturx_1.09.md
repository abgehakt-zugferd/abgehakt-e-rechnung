# ZUGFeRD 2.5 / Factur-X 1.09: Wissensdatenbank

Stand: 2026-06-11 | Quelle: FeRD-Spezifikation ZUGFeRD 2.5.0, veröffentlicht 10.06.2026, gültig ab **30.06.2026**

---

## Was ist ZUGFeRD 2.5 / Factur-X 1.09?

ZUGFeRD 2.5 ist die deutsche Bezeichnung, Factur-X 1.09 die französische für dieselbe Spezifikation.
Basiert auf **UN/CEFACT CII D22B** (statt bisher D16B) und erfüllt EN 16931.
Dateien im Paket: Hauptspezifikation, technische Anhänge je Profil, Code-Listen, Beispiel-Rechnungen.

---

## ⚠️ KRITISCHE ÄNDERUNG: EN16931 Profile-ID

Die Profile-ID (BT-24, `GuidelineSpecifiedDocumentContextParameter/ID`) hat sich geändert:

| Profil | Alt (ZUGFeRD 2.3) | Neu (ZUGFeRD 2.5) |
|--------|-------------------|-------------------|
| **EN16931** | `urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:en16931` | **`urn:cen.eu:en16931:2017`** |
| BASIC | `urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic` | unverändert |
| MINIMUM | `urn:factur-x.eu:1p0:minimum` | unverändert |
| EXTENDED | `urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:extended` | unverändert |

**→ `PROFILE_IDS["EN16931"]` in `backend/app/services/zugferd_xml.py` muss auf `urn:cen.eu:en16931:2017` aktualisiert werden.**

---

## Hauptänderungen gegenüber ZUGFeRD 2.3

1. **Basierung auf UN/CEFACT CII D22B** (statt D16B)

2. **BG-3 (Bezugsdokument) jetzt 0..n**: mehrere Bezugsdokumente je Rechnung möglich (alle Profile außer MINIMUM)

3. **Kardinalitätsänderungen im EN16931-Profil:**
   - `BT-47` (Amtliche ID Käufer): 0..1 (geändert)
   - `BT-61` (Amtliche ID Zahlungsempfänger): 0..1 (geändert)
   - `BG-16` (Zahlungsmittel/Bankkonten): 0..n → mehrere Bankkonten möglich

4. **Neue Code-Listen:**
   - Gültig ab 15.05.2025 und 15.11.2024 (rückwirkend in Spezifikation)
   - TypeCode `389` für Gutschriftverfahren (Selbstausstellung) explizit hinzugefügt

5. **BASIC/BASIC-WL bekommt neue Felder:** BT-6, BT-20, BT-111, BT-127, BT-147, BT-148
   (nicht relevant für unser EN16931-Profil)

6. **CountrySubDivisionName** (BT-39, BT-54, BT-68 etc.) in BASIC-Profil neu

---

## EN16931-Profil: Pflichtfelder (Mandatory, 1..1 oder 1..n)

### Dokumentebene

| BT | Beschreibung | XML-Pfad (gekürzt) | Typ |
|----|-------------|---------------------|-----|
| BT-24 | Spezifikationskennung | `ExchangedDocumentContext/GuidelineSpecifiedDocumentContextParameter/ID` | ID |
| BT-1 | Rechnungsnummer | `ExchangedDocument/ID` | ID |
| BT-3 | Rechnungstyp-Code | `ExchangedDocument/TypeCode` | Code |
| BT-2 | Rechnungsdatum | `ExchangedDocument/IssueDateTime/DateTimeString` | Date (YYYYMMDD) |
| BT-5 | Währung | `ApplicableHeaderTradeSettlement/InvoiceCurrencyCode` | Code |

### Verkäufer (BG-4 + BG-5)

| BT | Beschreibung | Pflicht |
|----|-------------|---------|
| BT-27 | Name Verkäufer | 1..1 |
| BT-35 | Straße Verkäufer | 1..1 |
| BT-37 | PLZ Verkäufer | 1..1 |
| BT-162 | Stadt Verkäufer | 1..1 |
| BT-40 | Land Verkäufer (2-stellig) | 1..1 |
| BT-29 | Kennung Verkäufer (`SellerTradeParty/ID`) | siehe `BR-CO-26` unten |
| BT-30 | Registernummer Verkäufer (`SpecifiedLegalOrganization/ID`) | siehe `BR-CO-26` unten |
| BT-31 | USt-IdNr. Verkäufer (schemeID="VA") | bedingt pflicht (min. eines von BT-31/BT-32) |
| BT-32 | Steuernummer Verkäufer (schemeID="FC") | bedingt pflicht (min. eines von BT-31/BT-32) |

⚠️ **`BR-CO-26` ist eine ZWEITE, unabhängige Bedingung, und BT-32 erfüllt sie nicht.**
Die Regel verlangt mindestens eines von **BT-29, BT-30 oder BT-31**. Die deutsche
Bedingung „BT-31 oder BT-32" darüber ist damit **nicht** deckungsgleich: Wer nur eine
Steuernummer hat (kein § 19-Sonderfall, sondern der Normalfall bei Einzelunternehmen),
erfüllt sie und scheitert trotzdem an `BR-CO-26`. Mustang meldet dann
`XML:invalid` und die Rechnung entsteht gar nicht.

Am 2026-08-09 in der Abnahme an einer echten Erstinstallation gemessen: nur
Steuernummer ⇒ `XML:invalid`; mit USt-IdNr. ⇒ `XML:valid`; nur Steuernummer, diese
zusätzlich als BT-29 ⇒ `XML:valid`. Das Programm gibt deshalb die Steuernummer als
BT-29 aus, wenn keine USt-IdNr. hinterlegt ist (`zugferd_xml._seller_id_xml`).

### Käufer (BG-7 + BG-8)

| BT | Beschreibung | Pflicht |
|----|-------------|---------|
| BT-44 | Name Käufer | 1..1 |
| BT-50 | Straße Käufer | 1..1 |
| BT-53 | PLZ Käufer | 1..1 |
| BT-52 | Stadt Käufer | 1..1 |
| BT-55 | Land Käufer | 1..1 |

### MwSt.-Aufschlüsselung (BG-23 pro Steuersatz)

| BT | Beschreibung | Pflicht |
|----|-------------|---------|
| BT-117 | MwSt.-Betrag | 1..n |
| BT-116 | MwSt.-Basis | 1..n |
| BT-119 | MwSt.-Satz | 1..n |
| BT-118 | MwSt.-Kategorie-Code | 1..n |

### Gesamtbeträge (BG-22)

| BT | Beschreibung | Pflicht |
|----|-------------|---------|
| BT-106 | Netto-Gesamtbetrag (LineTotalAmount) | 1..1 |
| BT-109 | MwSt.-Basis (TaxBasisTotalAmount) | 1..1 |
| BT-110 | MwSt.-Betrag gesamt | 1..1 |
| BT-112 | Brutto-Gesamtbetrag (GrandTotalAmount) | 1..1 |
| BT-115 | Zahlbetrag (DuePayableAmount) | 1..1 |

### Rechnungsposition (BG-25)

| BT | Beschreibung | Pflicht |
|----|-------------|---------|
| BT-126 | Positions-ID | 1..1 |
| BT-153 | Positionsbezeichnung | 1..1 |
| BT-146 | Nettopreis | 1..1 |
| BT-129 | Menge | 1..1 |
| BT-130 | Mengeneinheit (UN/CEFACT-Code) | 1..1 |
| BT-151 | MwSt.-Kategorie Position | 1..1 |
| BT-152 | MwSt.-Satz Position | 1..1 |
| BT-131 | Nettobetrag Position | 1..1 |

---

## MwSt.-Kategorie-Codes (BT-118, BT-151)

| Code | Bedeutung | Steuersatz-Beispiel |
|------|-----------|---------------------|
| `S` | Normaler Steuersatz | 19%, 7% |
| `Z` | Nullsatz | 0% |
| `E` | Steuerbefreit | 0% (§ 4 UStG) |
| `AE` | Reverse Charge (Umkehr Steuerschuld) | 0% |
| `K` | Innergemeinschaftliche Lieferung | 0% |
| `G` | Außerhalb EU | 0% |
| `O` | Nicht steuerbar | 0% |
| `L` | IGIC (Kanarische Inseln) | n/a |
| `M` | IPSI (Ceuta/Melilla) | n/a |

**Unsere App** setzt aktuell nur `S` (bei > 0%) und `Z` (bei 0%). Korrekte Zuordnung für:
- Steuerfreie Lieferungen § 4 UStG → `E`
- Reverse Charge B2B EU → `AE`
- EU-Lieferungen → `K`

---

## TypeCodes (BT-3)

| Code | Bedeutung |
|------|-----------|
| `380` | Rechnung (standard) |
| `381` | Gutschrift (Kreditnote) |
| `384` | Rechnungskorrektur |
| `389` | Gutschriften im Gutschriftverfahren (Selbstausstellung) |
| `751` | Buchungshilfe |

---

## Business Rules (BR-Codes) nach EN16931

Wichtigste Regeln für unsere Implementierung:

| BR-Code | Regel |
|---------|-------|
| BR-1 | Rechnung muss genau eine `ID` haben |
| BR-2 | Rechnung muss genau ein `IssueDateTime` haben |
| BR-3 | Rechnungs-Datum im Format YYYYMMDD |
| BR-4 | TypeCode muss aus erlaubter Liste (UNTDID 1001) sein |
| BR-10 | Verkäufername darf nicht leer sein |
| BR-15 | Käufername darf nicht leer sein |
| BR-16 | `GrandTotalAmount = TaxBasisTotalAmount + TaxTotalAmount` |
| BR-17 | `DuePayableAmount = GrandTotalAmount - (Prepaid)` |
| BR-21 | Zahlungsfälligkeitsdatum ≥ Rechnungsdatum |
| BR-22 | `BilledQuantity > 0` (außer Kreditnoten) |
| BR-25 | `LineTotalAmount = BilledQuantity × NetPriceProductTradePrice` |
| BR-26 | `NetPriceProductTradePrice ≥ 0` |
| BR-27 | `NetPriceProductTradePrice = GrossPriceProductTradePrice - Rabatt` |
| BR-54 | MwSt.-Kategorie-Code aus erlaubter Liste (S/Z/E/AE/K/G/O/L/M) |
| BR-64 | `LineTotalAmount = Summe aller Positions-LineTotalAmount` |
| BR-65 | Steuerbetrag korrekt aus Steuerbasis und Steuersatz berechnet |

---

## Optionale aber empfohlene Felder (EN16931)

| BT | Beschreibung | Wann relevant |
|----|-------------|---------------|
| BT-23 | Geschäftsprozesstyp | Wenn Prozess-ID bekannt |
| BT-9 | Fälligkeitsdatum | Immer empfohlen (BT-9 + BT-81) |
| BT-80 | Lieferdatum | § 14 Abs. 4 Nr. 6 UStG, Pflicht > 250 € |
| BT-81 | Zahlungsmittel-Code | Mit IBAN: Code 58 (SEPA) |
| BT-84 | IBAN | Zahlungsmittel SEPA |
| BT-85 | BIC | Optional bei SEPA |
| BT-48 | USt-IdNr. Käufer | § 14a UStG bei Betrag > 10.000 € |
| BT-22 | Freitext | Allgemeine Hinweise |

---

## Implementierungslücken unserer App (Stand 2026-06-11)

### Kritisch (spec-non-konform):
- **Profile-ID EN16931 veraltet** → `zugferd_xml.py` Zeile 13 korrigieren
- ~~**MwSt.-Kategorie nur S/Z** → E, AE, K für steuerfreie Rechnungen fehlen~~
  erledigt: S/Z/AE/K/O, seit 09.08.2026 auch E (§ 19 UStG, #152). Offen bleibt nur
  G (Ausfuhr Drittland). ⚠️ Zu jeder Kategorie ohne Steuer gehört ein Befreiungsgrund,
  sonst ist die Rechnung schema-ungültig: `BR-E-10` für E, entsprechend für AE/K/O.
  Die Gründe stehen in `zugferd_xml.EXEMPTION_REASONS` und werden vom PDF von dort
  bezogen, nicht kopiert.

### Wichtig:
- BT-23 (Geschäftsprozesstyp) nicht implementiert
- BT-127 (Positions-Freitext) nicht implementiert
- BT-85 (BIC) ist implementiert ✓
- BT-80 (Lieferdatum) ist implementiert ✓

### Nice-to-have:
- BT-46 (Käufer-ID), BT-71 (Verkäufer-ID) fehlen
- Mehrere Bankkonten (BG-16 0..n) nicht unterstützt
- TypeCode 381/384/389 für Gutschriften/Korrekturen nicht dynamisch

---

## Beispieldateien im Paket (ZF25_DE)

Verzeichnis: `knowledge/ZUGFeRD/ZF25_DE/Beispiele/3. EN16931/`

| Kürzel | Szenario |
|--------|----------|
| E05_Einfach | Einfache Rechnung 19% |
| E10_Gutschrift | Gutschrift (TypeCode 381) |
| E13_Kleinunternehmer | Ohne USt-IdNr., §19 UStG |
| E19_Rabatte | Positionen mit Rabatten |
| E20_Rechnungskorrektur | TypeCode 384 |
| E24_SEPA_Prenotification | SEPA-Lastschrift |
| E25_steuerbefreite_Auslandslieferung | Kategorie K |

---

## Quellen

- `knowledge/ZUGFeRD/ZF25_DE/Dokumentation/0_FACTUR-X 1.09 2026 06 10 DE.pdf` (→ txt)
- `knowledge/ZUGFeRD/ZF25_DE/Dokumentation/6_ZugFeRD_2.5_Technischer_Anhang_Profil_EN16931.pdf` (→ txt)
- FeRD-Website: www.ferd-net.de
