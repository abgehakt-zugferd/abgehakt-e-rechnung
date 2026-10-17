# Auftrag: Gutschriftverfahren (BT-3 389) als eigener Belegweg

**Status:** teilweise umgesetzt.

Umgesetzt:

- Steuerstatus am Kunden: `services/steuerstatus.py` mit `pruefe_honorargutschrift`, aufgerufen aus dem Validator.
- Steuernummer am Kunden: `Customer.tax_number`, Formularfeld und Prüfung beim Finalisieren.
- Vorsteuer in den Kennzahlen: `vorsteuer_honorargutschriften` in `dashboard_kennzahlen.py`, abgezogen in `geschaetzte_steuerabgaben`.
- Befreiungshinweis nach § 34a UStDV: `EXEMPTION_SELF_BILLING_E` in `zugferd_xml.py`.
- Rollentausch: `services/belegrollen.py` besetzt Verkäufer und Erwerber für XML und PDF.
- Originalbezug: `self_billing` trägt `braucht_original=False`; ein Bezug wird abgewiesen.
- Pflichtangabe „Gutschrift" als systemseitige BT-22-Note, unabhängig von Nutzernotizen.

Offen:

- Eigener Titel für 381: `Belegdarstellung.titel` in `belegsprache.py` bildet `credit_note` und `self_billing` auf denselben Titel ab.
- Storno-Sperre für 389: `pruefe_stornierbar` in `storno.py` und `create_storno` in `routers/invoices.py` sperren nur `credit_note`.
- Manuelle Anlage: `self_billing` steht in `belegart.py` auf `manuell_waehlbar=False`.
- Herleitung speichern: `InvoiceItem` hat keine Spalten für `basis_netto` und `satz`.
- Art-Filter `honorargutschrift`: `filtere_rechnungsliste` in `rechnungsliste_filter.py` kennt nur `rechnung` und `gutschrift`.
- Kennzahl offene Auszahlungen: `dashboard_kennzahlen.py` führt keine solche Kennzahl.
- Ablehnung des Nullbetrags: der Validator kennt `ITEM_PRICE_NEGATIVE`, aber keine Ablehnung eines Nettobetrags von null bei 389.

## Anlass

Abgehakt kann heute keine Vergütung für eingeräumte Nutzungsrechte, Beteiligungen oder
Provisionen im Gutschriftverfahren ausstellen. Der Integrationsweg (Absender
`ABSENDER_TANTIEMEN` in `services/uebergabebeleg.py`) legt Entwürfe an, aber sie lassen
sich nicht finalisieren, und die erzeugte XML wäre fachlich falsch.

Die Ursache ist der bekannte falsche Freund des deutschen Umsatzsteuerrechts. Zwei
verschiedene Dinge heißen gleich:

| | kaufmännische Gutschrift | Gutschrift nach § 14 Abs. 2 UStG |
|---|---|---|
| BT-3 | 381 | 389 |
| Was sie ist | Korrektur einer bestehenden Rechnung | vollwertige Rechnung, ausgestellt vom Leistungsempfänger |
| Originalbezug | notwendig | es gibt kein Original |
| Aussteller | der Leistende | der Leistungsempfänger |
| Leistender | der Aussteller | die Gegenseite |

Der Fall der vergüteten Nutzungsrechte, Beteiligungen oder Provisionen ist der rechte Fall:
Der Leistende, etwa ein Urheber, räumt Nutzungsrechte ein oder erbringt die Leistung, und
der Leistungsempfänger stellt den Beleg aus. Dass es kein Original gibt, ist kein
Sonderfall, sondern das Wesen des Verfahrens.

## Namen: drei Dinge dürfen nicht gleich heißen

Heute drucken 381 und 389 denselben Titel. `Belegdarstellung.titel` in `belegsprache.py`
bildet `credit_note` und `self_billing` beide auf `titel_gutschrift` ab, also auf
`GUTSCHRIFT` beziehungsweise `CREDIT NOTE`. Damit ist
am fertigen Beleg nicht zu erkennen, welcher der beiden Fälle vorliegt.

Das ist mehr als unschön. Die Angabe „Gutschrift" ist nach § 14 Abs. 4 S. 1 Nr. 10 UStG die
**Pflichtangabe für das Gutschriftverfahren**. Steht sie auf einer Stornorechnung, behauptet
der Beleg, der Empfänger habe ihn ausgestellt. Umgekehrt fehlt sie dem 389, wenn man den
Titel für den Storno entschärft, ohne beide zu trennen.

Die Spec legt deshalb drei verschiedene Bezeichnungen fest, in Oberfläche, PDF und
Dokumentation:

| Belegart | BT-3 | heißt ab jetzt | heißt **nicht** |
|---|---|---|---|
| Storno einer eigenen Rechnung | 381 | Stornorechnung | Gutschrift |
| Abrechnung über eine fremde Leistung | 389 | Honorargutschrift (Gutschriftverfahren) | Gutschrift einer Rechnung |
| Korrektur | 384 | Korrekturrechnung | unverändert |

Der 389 behält das Wort „Gutschrift" im Titel, weil das Gesetz es verlangt. Der 381 gibt es
ab, weil er es nie tragen durfte. Die Oberfläche nennt beim Anlegen zusätzlich den Zweck,
damit niemand die Honorargutschrift für die Korrektur einer Rechnung hält.

## Gemessener Ist-Stand (2026-09-30)

Der Code kennt 389 bereits an drei Stellen richtig: `TYPCODE_BELEGART` in
`abrechnungsauftrag_wirkung.py` trennt 389 von 381, die Steuer wird aus dem Status des
Kunden abgeleitet, und `_gutschrift_zahlung_an_kunde` in `zugferd_xml.py` lässt die
Zahlung bei 389 an den Kunden gehen. Falsch ist nicht alles,
sondern eine bestimmte Annahme: dass der Verkäufer immer die eigene Firma ist.

Fünf Befunde, jeder am Quelltext belegt:

1. **`belegart.py`**: `_SELF_BILLING` trägt `braucht_original=True`. Gemessen mit einem
   Beleg, wie der Integrationsweg ihn anlegt: `ORIGINAL_INVOICE_REQUIRED` für 389 **und**
   381, nicht für 380.
2. **`zugferd_xml.py`**: `SellerTradeParty` wird bedingungslos aus der
   eigenen Firma gefüllt, `BuyerTradeParty` bedingungslos aus dem Kunden. Für 389 steht
   damit die falsche Steuerkennung im Pflichtfeld.
3. **`exemption_reason` in `zugferd_xml.py`**: Der frühere Befreiungstext für 389 setzte
   voraus, dass der Beteiligte der Leistende ist, während der Verkäufer-Knoten das
   Gegenteil behauptete. Behoben in #148: der Befreiungshinweis trägt den neuen Wortlaut
   nach § 34a Satz 1 Nr. 5 UStDV, „Steuerbefreiung für Kleinunternehmer gemäß § 19 UStG."
   (`EXEMPTION_SELF_BILLING_E`).
4. **`models/customer.py`**: Ein Kunde hat `vat_id` und seit dem Steuerstatus-Auftrag auch
   `tax_number` (Feld, Formular, Prüfung beim Finalisieren). **Offen bleibt die XML-Ausgabe**
   mit getauschten Rollen (`zugferd_xml.py` unberührt). Die Firma hat beides schon länger
   (`Company.tax_number`).
5. **`create_storno` in `routers/invoices.py`**: Storniert werden darf alles außer
   `credit_note`. Ein finalisierter 389 fällt nicht darunter, und `build_storno` in
   `storno.py` erzeugt daraus einen 381,
   also einen Beleg mit zurückgedrehten Rollen.

Dazu: **`entwuerfe_anlegen` in `abrechnungsauftrag_wirkung.py`** setzt `original_invoice_id`
nicht, und **kein
Test führt einen importierten Entwurf durch die Finalisierung**. Der vorhandene
`test_abrechnungsauftrag_wirkung.py` prüft die Anlage, nicht den Beleg; die 389-Tests des
Validators arbeiten mit Attrappen.

## Rechtsrahmen, mit Fundstelle

- **Gutschrift** = Abrechnung durch den Leistungsempfänger, § 14 Abs. 2 UStG. Der geltende
  Gesetzestext in § 14 Abs. 4 S. 1 Nr. 10 verweist auf „Absatz 2 Satz 5"; XRechnung 3.0.2
  (Abschnitt 13.1) und UStAE 14.3 zitieren noch „Abs. 2 Satz 2". Beide Fassungen sind hier
  festgehalten, weil die Pflichtangabe selbst unstreitig in § 14 Abs. 4 S. 1 Nr. 10 steht.
- **Pflichtangabe „Gutschrift"**, § 14 Abs. 4 S. 1 Nr. 10 UStG: „in den Fällen der
  Ausstellung der Rechnung durch den Leistungsempfänger … die Angabe ‚Gutschrift'".
- **Steuernummer oder USt-IdNr. des leistenden Unternehmers**, § 14 Abs. 4 S. 1 Nr. 2 UStG.
  Das ist der Leistende.
- **Einvernehmen vor der Abrechnung**, UStAE 14.3. Wird mit der Gegenstelle im Vertrag zur
  Vergütung vereinbart.
- **7 %** auf die Einräumung von Nutzungsrechten, § 12 Abs. 2 Nr. 7c UStG.
- **Kleinunternehmer**: kein Ausweis, dafür Hinweis auf die Befreiung und die Angabe
  „Gutschrift", § 34a UStDV. Unrichtiger Ausweis löst § 14c UStG aus.

## Format, mit Fundstelle

Recherchiert am 2026-09-30 gegen die Primärquellen:

- **389 ist zulässig.** Es steht in der für BR-CL-01 erlaubten UNTDID-1001-Menge des
  EN16931-CII-Schematrons; XRechnung 3.0.2 führt es als „Self-billed invoice", BR-DE-17
  nennt es als empfohlenen Code. Nicht erlaubt in MINIMUM und BASIC WL, die dieses Programm
  ohnehin nicht schreibt.
- **Die Rollen bleiben, die Besetzung dreht sich.** BG-4 ist weiterhin der Verkäufer, BG-7
  der Erwerber. Da 389 laut Codeliste „vom Rechnungsempfänger anstelle des Verkäufers"
  erzeugt wird, ist bei einer 389 der **Leistende der Seller (Verkäufer)** und der
  **Aussteller der Gutschrift der Buyer (Erwerber)**. Ein eigenes
  Feld für den Aussteller kennt EN 16931 nicht.
- **BG-3 ist im Standard bei 389 weder gefordert noch verboten**, Kardinalität 0..*.
  BR-DE-26 verlangt eine Vorgängerreferenz nur bei 384.
- **Für die Pflichtangabe „Gutschrift" gibt es kein eigenes Feld.** Der TypeCode trägt nur
  die englische Semantik. Transportort für den deutschen Wortlaut ist **BT-22**
  (`IncludedNote`), zusätzlich zur sichtbaren Darstellung im PDF.
- **Die Steuerkennung des Verkäufers hat zwei Wege**, und der Generator nutzt beide:
  BT-31 als `VA`-Registrierung für die USt-IdNr., BT-32 als `FC`-Registrierung für die
  Steuernummer (`_seller_tax_xml` in `zugferd_xml.py`), dazu BT-29 als Verkäuferkennung,
  wenn die USt-IdNr. fehlt (`_seller_id_xml` in derselben Datei). Alle drei gehören zur
  Rollenfrage, nicht nur BT-31.
- **Kein 389-abhängiger Sonderfall beim Steuerausweis.** Es gelten BG-23 und BT-116 bis
  BT-119 wie sonst. Für Kleinunternehmer: BT-118 = `E`, BT-117 = 0, BT-119 = 0,
  Befreiungstext in BT-120.

Nicht belegbar und deshalb offen: dass genau Mustang-CLI 2.24.0 eine vollständige
389-Instanz annimmt. Die Codeliste beweist die Zulässigkeit des Codes, nicht die
Verarbeitung einer Instanz. **Das wird am laufenden Container gemessen, bevor dieser
Auftrag als erledigt gilt.**

## Der Schnitt: eine Quelle für die Rollenbesetzung

Die naheliegende Umsetzung wäre, an jeder betroffenen Stelle `if invoice_type ==
"self_billing"` zu schreiben. Das wäre dieselbe Entscheidung an mindestens sechs Orten,
und beim siebten fällt sie aus. Der Beleg wäre dann halb gedreht, und das ist schlimmer
als gar kein 389.

Stattdessen ein eigenes Modul `services/belegrollen.py` mit einer kleinen Schnittstelle:

```python
def besetzung(invoice, company, customer) -> Besetzung:
    """Wer ist auf diesem Beleg Verkäufer (BG-4), wer Erwerber (BG-7)."""
```

`Besetzung` trägt `verkaeufer` und `erwerber`, jeweils als das Objekt, dessen Stammdaten
gelten, dazu `verkaeufer_ist_firma` für die Fälle, die eine Fallunterscheidung wirklich
brauchen. Bei 380, 381, 384 und 386 ist der Verkäufer die Firma, bei 389 der Kunde.

**Was dieses Modul ausdrücklich NICHT beantwortet**, obwohl es heute zufällig
zusammenfällt:

| Frage | Wer | Warum nicht hier |
|---|---|---|
| Wer bekommt das Geld? | schon heute richtig: bei 389 der Kunde (`_gutschrift_zahlung_an_kunde` in `zugferd_xml.py`, EPC-QR über `_zahlung_an_kunde` in `pdf_generator.py`) | Zahlungsempfänger ist eine eigene Frage. Bei einer Gutschrift an einen Kleinunternehmer könnte sie anders ausgehen als die Verkäuferrolle. |
| Wer bekommt die Mail? | der Kunde (Versandroute in `routers/invoices.py`) | Versandempfänger ist der Adressat des Belegs, nicht der Leistende. |
| Wer fragt bei VIES an? | die Firma fragt, der Kunde wird geprüft (`pruefe_ust_id_vies` in `services/ust_id_pruefung.py`, aufgerufen aus `routers/customers.py`) | Der Anfragende ist immer die eigene Firma, unabhängig von der Belegart. |

Diese drei Zuordnungen sind heute korrekt und dürfen beim Umbau **nicht** mitgetauscht
werden. Ein globales Vertauschen von `company` und `customer` würde funktionierende Wege
beschädigen.

Die Probe auf den Schnitt: Nähme man `belegrollen` wieder heraus, erschiene dieselbe
Fallunterscheidung im XML-Generator (Verkäuferblock, Erwerberblock, Adresszusatz über
`bereinige_adresszeile2` aus `services/adresse.py`, Steuerregistrierung), im Validator
(Pflichtfelder und Rollennamen der
Befunde) und im PDF-Erzeuger. Das Modul trägt also etwas, statt nur durchzureichen.

## Ergebnis und fachlicher Umfang

1. **389 verliert den Pflichtbezug, und zwar ohne neue Lücke.** `braucht_original` ist ein
   Schalter mit zwei Stellungen, und `False` heißt heute nicht „optional", sondern
   „verboten": der Validator meldet dann `ORIGINAL_INVOICE_NOT_ALLOWED`. Für 389 ist
   das die **gewollte** Stellung, weil diese Anwendung kein Original kennt, auf das ein 389
   zeigen könnte. Die Spec entscheidet das hiermit ausdrücklich: **ein 389 trägt in dieser
   Anwendung nie einen Originalbezug.** Der Standard erlaubt mehr; wir nutzen es nicht.
2. **Die Rollen kommen aus `belegrollen.besetzung`.** Umzustellen sind Verkäufer- und
   Erwerberblock, Verkäuferkennung, Steuerregistrierung, Verkäuferkontakt, elektronische
   Adressen und die Adresszusatz-Aufbereitung. Im PDF ebenso, samt der Steuernummer im Fuß
   (`pdf_fuss.py`) und der Kundenkennung im Kopf (`pdf_generator.py`).
   Die Erwerber-USt-IdNr. im PDF-Kopf bleibt BT-48 zugeordnet, bei 389 also der
   eigenen Firma. Die Steuerkennung im Fuß gehört dagegen dem Verkäufer.
   Fundstelle: [EN-16931-Zuordnung BT-48 bei OpenPeppol](https://docs.peppol.eu/poacc/billing/3.0/syntax/ubl-invoice/cac-AccountingCustomerParty/cac-Party/cac-PartyTaxScheme/cbc-CompanyID/).
   Der XML-Rückimport sucht den externen Kunden bei TypeCode 389 deshalb im
   Verkäuferblock, bei den übrigen Typen im Erwerberblock. Ersatzrechnungen
   bleiben ausdrücklich auf 380 und 386 als ersetzbare Belegarten beschränkt;
   die Originalbezugspflicht entscheidet darüber nicht. Die Korrektur einer
   falschen 389 durch Storno und Neuausstellung folgt in einem eigenen Schritt.
3. **Der Kunde bekommt eine Steuernummer.** Umgesetzt: Feld `Customer.tax_number`, Migration,
   Formularfeld, Speicherung, Prüfung beim Finalisieren einer 389. **Noch offen:** Ausgabe als
   `FC`-Registrierung in der XML (Rollenbesetzung). Nach § 9 des Übergabeformats darf sie
   **nicht** über den Übergabebeleg kommen: Steuernummern sind Stammdaten dieses Systems.
   Ebenso fehlt dem Kunden ein `contact_name`, den `_seller_contact_xml` liest; entweder wird
   er ergänzt oder die Funktion kommt ohne ihn aus.
4. **389 trägt die Pflichtangabe.** Die Zeichenfolge `Gutschrift` erscheint als
   systemseitiger Pflichttext in BT-22 und im sichtbaren PDF-Titel, in beiden
   Belegsprachen. Sie darf durch keine Nutzereingabe verschwinden.
5. **Der Steuerstatus gilt auch beim Finalisieren, nicht nur beim Import.** Umgesetzt
   (Abnahmekriterium 7): Modul `services/steuerstatus.py`, Voreinstellung `ungeklaert`,
   Schalter `gutschriftempfaenger`, Prüfung in `validate_invoice` für `self_billing` als
   Fehler. `regelbesteuert` erzwingt `S` und 7, `kleinunternehmer` erzwingt `E` und 0,
   jeweils am Belegkopf und an den Positionen. Die Ableitung beim Import nutzt dasselbe Modul.
6. **Die Herleitung wird gespeichert, gebunden und sichtbar.** Der Auftrag trägt je Position
   optional `herleitung {basis_netto, satz}`; Abgehakt rechnet sie schon nach und lehnt bei
   Abweichung ab (die Rechenprobe in `uebergabe_befund.py`, Übergabeformat § 8, „der
   Prüfhaken"). Heute werden beide Zahlen beim Anlegen verworfen. Sie gehören als Spalten
   an `InvoiceItem`, in
   die gebundenen Felder von `belegsperre.py` und auf den Beleg. Sonst verliert sie der
   erste erlaubte Text- oder Steueredit, weil `_replace_items` in `routers/invoices.py`
   alle Positionen löscht und neu anlegt.
   Der **Beteiligungssatz** ist nicht der Umsatzsteuersatz. Beide müssen getrennt dargestellt
   werden, und die Mengen- und Einzelpreisspalten der PDF-Tabelle in `pdf_generator.py`
   bleiben davon unberührt, tragen also weiter Menge 1 und den Nettobetrag.
7. **Ein finalisierter 389 lässt sich nicht stornieren.** `pruefe_stornierbar` und
   `create_storno` sperren heute nur `credit_note`. Solange keine fachlich richtige
   Korrektur eines Gutschriftverfahrens
   definiert ist, wird `self_billing` dort mitgesperrt, mit einer Meldung, die auf den
   Korrekturlauf der Gegenseite verweist.
8. **Die Bearbeitungssperre bleibt, wie sie ist.** `_get_draft` weist `credit_note` ab;
   `self_billing` fällt nicht darunter und soll es nicht, dafür gibt es `belegsperre.py`.
   Zu prüfen ist nur, dass die Meldung für 381 ihren Wortlaut behält.
9. **Eine Honorargutschrift lässt sich von Hand anlegen und bearbeiten.**
   `belegart.py` stellt `self_billing` auf `manuell_waehlbar=True` mit dem Formularwert
   `honorargutschrift` und der Beschriftung aus der Namenstabelle oben. Damit ist die
   Auszahlung nicht mehr davon abhängig, dass die Gegenseite einen signierten Auftrag
   liefert.
   Die Sperren richten sich dabei nach der **Herkunft**, nicht nach der Belegart:
   `belegsperre.gilt` prüft `uebergabe_beleg_sha256`, greift also nur bei Belegen aus der
   Integration. Eine von Hand angelegte Honorargutschrift ist ein gewöhnlicher Entwurf und
   bis zum Finalisieren frei bearbeitbar, Beträge eingeschlossen.
   `herleitung` ist bei ihr **optional**: es gibt keinen signierten Auftrag, gegen den sie
   zu prüfen wäre. Wird sie eingegeben, gilt dieselbe Rechenprobe wie beim Import.
   Alles andere gilt unverändert: Rollenbesetzung, Pflichtangabe, Steuerprüfung nach
   `ust_status`, kein Originalbezug, kein Nullbetrag, keine Stornierbarkeit.

## Was ausdrücklich NICHT gilt

Mit der Gegenstelle abgestimmt:

- **Es gibt kein Stückhonorar auf der Gutschrift.** Wird eine Beteiligung als Anteil an
  einer Bemessungsgrundlage vergütet, gibt es keinen Stückpreis; die Position zeigt
  Bemessungsgrundlage × Satz. Eine Zeile „Menge × Stückbetrag" wäre auf einem solchen
  Beleg eine erfundene Angabe. Die prüfbare Zerlegung heißt Bemessungsgrundlage × Satz.
- **Keine Werkkennung je Position.** Das Übergabeformat führt je Position nur Nummer,
  Bezeichnung, Betrag und die optionale Herleitung (Feldverzeichnis in `protokoll.py`);
  eine Position kann die Leistungen eines ganzen Abrechnungszeitraums zusammenfassen.
- **Kein Mengengerüst als Bemessung.** Die Menge ist nur Nachweis, nie
  Bemessungsgrundlage.
- **Keine negativen Positionen und kein Nullbetrag.** Ein negativer Anteil wird beim
  Sender zum Verlustvortrag, ein Anteil unter der Mindestauszahlung zu einem Eintrag in
  `vortraege[]`. Der Validator lehnt heute negative Preise ab (`ITEM_PRICE_NEGATIVE`),
  aber nicht die Null; für 389 ist auch sie abzuweisen.
- **Keine Kosten als Minusposten.** Übergabeformat § 8: Verwaltungsgebühr und Direktkosten
  sind in der Bemessungsgrundlage abgezogen und gehören, wenn sie berechnet werden, auf eine
  eigene Rechnung mit 19 %. Ebenso **keine KSA-Zeile**, § 32 KSVG verbietet die Abwälzung.
- **Aus `vortraege` entsteht keine Rechnungswirkung.** Die Feldprüfung liest die Liste
  strukturell (`_pruefe_objekt` in `uebergabe_befund.py`, das
  Feldverzeichnis in `protokoll.py`); ein Beleg wird daraus nicht.

## Die Übersicht: ein 389 zeigt in die andere Richtung

Eine Honorargutschrift ist wirtschaftlich das Gegenteil einer Ausgangsrechnung. Der
Aussteller der Gutschrift
schuldet Geld, statt welches zu bekommen, und die 7 % darauf sind **Vorsteuer**, kein
abzuführender Betrag. Das Programm ist aber durchgehend auf Ausgangsrechnungen gebaut;
`docs/ANWENDUNG.md` begründet die Kennzahl „Schuldige Umsatzsteuer" ausdrücklich damit,
dass es keine Eingangsrechnungen kenne. Ein 389 ist genau die eine Ausnahme davon.

**Gemessener Ist-Stand.** Heute ist die Behandlung nicht falsch, sondern uneinheitlich:

| Kennzahl | filtert auf | 389 enthalten? |
|---|---|---|
| Rechnungen gesamt, Status-Zählung | kein Typfilter (`belegzaehlung` in `dashboard_kennzahlen.py`) | **ja** |
| Offene und überfällige Forderungen, nicht versendet | `invoice_type IS NULL` | nein |
| Umsatz, bezahlt im Monat | `invoice_type IS NULL` | nein |
| Schuldige USt, Nettoumsatz, Rücklage | Standardrechnung ohne Typ (`schuldige_umsatzsteuer_ytd`, `nettoumsatz_ytd`) | nein |
| Liste, Filter `art=rechnung` / `art=gutschrift` | `IS NULL` / `credit_note` (`filtere_rechnungsliste` in `rechnungsliste_filter.py`) | **in keinem von beiden** |

Ein 389 wird also in den Belegzahlen mitgezählt, taucht in keiner Geldkennzahl auf und ist
über den Art-Filter nicht auffindbar. Wer die Übersicht liest, sieht eine Zahl im Kopf,
deren Belege er über die Filter nicht erreicht, und sieht von den Auszahlungsverpflichtungen
nichts.

**Was dieser Auftrag festlegt:**

1. **Der Art-Filter bekommt einen dritten Wert.** `art=honorargutschrift` filtert auf
   `invoice_type == 'self_billing'`. Ohne ihn bleibt ein Beleg unerreichbar, den die
   Übersicht mitzählt.
2. **Die Geldkennzahlen der Ausgangsseite bleiben unberührt.** Umsatz, offene Forderungen
   und schuldige Umsatzsteuer sind Zahlen über das, was der Betreiber einnimmt und
   abführt. Ein 389
   gehört dort nicht hinein, und zwar nicht aus Bequemlichkeit, sondern weil er die andere
   Richtung hat. Die heutige Ausklammerung ist also richtig und wird als Absicht
   festgeschrieben, nicht als Zufall stehen gelassen.
3. **Die Übersicht bekommt einen eigenen Block für die Auszahlungsseite** mit zwei
   Kennzahlen: **Offene Auszahlungen** (Anzahl und Bruttosumme gestellter, noch nicht
   bezahlter Honorargutschriften) und **Vorsteuer aus Honorargutschriften** (Summe der
   ausgewiesenen USt im laufenden Jahr). Beide verlinken auf die Liste mit dem neuen
   Art-Filter, wie die übrigen Kennzahlen auch.
4. **Die Doku wird mitgezogen.** Der Satz „das Programm kennt keine Eingangsrechnungen" in
   `docs/ANWENDUNG.md` und `README.md` stimmt danach nicht mehr uneingeschränkt und ist zu
   schärfen: es kennt keine **fremden** Eingangsrechnungen, wohl aber die selbst
   ausgestellte Honorargutschrift.

**Eine Entscheidung liegt beim Betreiber, nicht bei der Umsetzung.** Die Kennzahl
„Geschätzte Steuerabgaben" ist ausdrücklich für die Rücklagenplanung gedacht. Dort wäre die
Vorsteuer aus Honorargutschriften sachlich abzuziehen, weil sie die tatsächliche Zahllast
mindert. Das ändert aber die Bedeutung einer dokumentierten Zahl.

- **Empfehlung:** abziehen, und zwar nur dort, nicht in „Schuldige Umsatzsteuer". Die eine
  Zahl beschreibt die Ausgangsseite, die andere plant die Zahlung.
- **Gegenargument:** Wer die Rücklage lieber zu hoch als zu niedrig bildet, lässt es.

**Entschieden am 2026-09-30 durch den Betreiber: abziehen**, wie empfohlen. Die Vorsteuer aus
gestellten und bezahlten Honorargutschriften seit Jahresanfang wird in „Geschätzte
Steuerabgaben" abgezogen und in der Kachel als eigene Zeile ausgewiesen; „Schuldige
Umsatzsteuer" bleibt unverändert. Übersteigt die Vorsteuer die USt, wird die Differenz nicht
bei null gekappt, weil eine Erstattung die Rücklage tatsächlich mindert. Festgehalten in
`test_dashboard_honorargutschrift.py`.

## Abnahmekriterien

Jedes Kriterium nennt den Zustand, in dem es rot sein muss.

1. Ein importierter, sonst vollständiger 389 ohne Originalbezug **finalisiert erfolgreich**.
   Ein 389 **mit** gesetztem Bezug wird abgewiesen. 381 und 384 ohne Bezug werden weiterhin
   abgewiesen. Geprüft wird der Ausgang des Finalisierens, nicht die Anwesenheit eines
   einzelnen Fehlercodes.
2. In der XML eines 389 tragen Verkäufer- und Erwerberblock durchgehend die Daten der
   jeweils richtigen Partei: Name, beide Adresszeilen, Postleitzahl, Ort, Land,
   elektronische Adresse, Kontakt und Kennungen. Die Testdaten beider Parteien sind
   **vollständig verschieden**, damit kein Feld zufällig passt. Für 380, 386, 381 und 384
   läuft derselbe Test als Regression mit umgekehrter Erwartung.
3. Die Steuerkennung des Verkäufers bei 389 ist die des Kunden, in vier Fällen geprüft: nur
   Steuernummer, nur USt-IdNr., beides, nichts. Im letzten Fall bricht das Finalisieren mit
   einem gezielten Befund ab, der Beleg bleibt `draft`, und im Archiv liegt nichts.
4. Die XML eines 389 trägt die Pflichtangabe an ihrem BT-22-Pfad auch dann, wenn die
   Notizen des Nutzers leer sind oder etwas anderes sagen.
5. Das sichtbare PDF eines 389 trägt `Gutschrift` im Titel, in `de` und in `en`. Ein
   englischer 381 wird als Regression mitgeprüft, weil beide sich heute denselben Titel
   teilen (`Belegdarstellung.titel` in `belegsprache.py`).
6. Mehrere Positionen mit verschiedenen Grundlagen und Sätzen werden importiert,
   gespeichert, neu geladen und **bearbeitet**; danach steht je Position die unveränderte
   Herleitung auf dem Beleg. Beteiligungssatz und Umsatzsteuersatz sind getrennt erkennbar.
7. Ein Kunde mit `ust_status='kleinunternehmer'` erzeugt `E`, Satz 0 und den Befreiungstext;
   ein regelbesteuerter erzeugt `S` und 7. Wird die Kombination nachträglich auf etwas
   anderes geändert, scheitert das Finalisieren.
8. Der vollständige Weg von der Einlesung bis zum Archiv läuft gegen die echte Datenbank
   durch, und Mustang liefert `is_valid` **und** `XML:valid` für das kombinierte PDF. Das
   ist dieselbe UND-Bedingung wie beim Finalisieren in `routers/invoices.py`;
   `XML:valid` allein genügt
   nicht. Scheitert eine Stufe, liegt am Ende kein Beleg im Archiv.

9. Das Anlegeformular bietet die Honorargutschrift an. Ein von Hand angelegter 389 lässt
   sich bearbeiten, Beträge eingeschlossen; ein aus einem signierten Beleg entstandener 389
   lässt die gebundenen Felder nicht ändern. Geprüft wird beides am selben Belegtyp, damit
   sichtbar bleibt, dass die Herkunft entscheidet und nicht die Belegart.
10. Ein 381 trägt im PDF **nicht** das Wort „Gutschrift", ein 389 trägt es, in `de` und
    `en`. Dieselbe Probe läuft gegen die Bezeichnung im Anlegeformular und in der Liste.
11. Die Liste kennt `art=honorargutschrift`; der Filter zeigt genau die 389 und kein
    anderer Art-Filter zeigt sie mit.
12. Ein gestellter 389 erhöht **nicht** Umsatz, offene Forderungen oder schuldige
    Umsatzsteuer, wohl aber die neuen Kennzahlen Offene Auszahlungen und Vorsteuer aus
    Honorargutschriften. Der Test prüft beide Richtungen an demselben Beleg; ein Test, der
    nur die neuen Zahlen ansieht, übersähe genau den Fehler, um den es hier geht.

## Tests

Alles mit Datenbankwirkung gehört in einen Integrationstest mit der `pg_session`-Fixture.
Neu, mindestens:

- `test_belegrollen.py`: die Besetzung je Belegart, als reiner Einheitentest.
- `test_belegart.py`: `self_billing` ohne Original, `credit_note` und `correction` mit.
- `test_zugferd_xml_389.py`: Kriterien 2, 3 und 4, per XPath auf die erzeugte XML, nicht per
  Zeichenkettenvergleich.
- `test_validator_389.py`: Kriterien 1, 3 und 7.
- `test_abrechnungsauftrag_wirkung.py` erweitern: ein importierter Entwurf wird validiert
  und finalisiert. Dieser Weg fehlt heute ganz und ist der Grund, warum die Befunde nicht
  aufgefallen sind.
- `test_herleitung_ueberlebt_bearbeitung.py`: Kriterium 6, ausdrücklich mit einem
  Bearbeitungsschritt dazwischen.
- `test_storno_389_gesperrt.py`: Umfang 7.
- `test_honorargutschrift_manuell.py`: Kriterium 9, mit beiden Herkünften.
- `test_belegtitel_trennung.py`: Kriterium 10, gegen das erzeugte PDF, nicht gegen die
  Titelkonstante.
- `test_dashboard_honorargutschrift.py`: Kriterien 11 und 12, als Integrationstest mit
  echten Belegen beider Arten in derselben Datenbank.
- `test_finalize_389_e2e.py`: Kriterium 8, im Container, mit echtem Mustang. Übersprungene
  Tests gelten hier als Fehlschlag; fehlt Mustang, ist der Lauf rot.

Nach dem Umbau die Gegenprobe: einen winzigen Fehler einbauen und sicherstellen, dass
mindestens ein Test rot wird. Bei `braucht_original` und bei `belegrollen` **beide** Zweige
brechen, nicht nur einen.

## Nicht in diesem Auftrag

- **Die Anlage mit dem Erlösnachweis** (Issue #121). Sie braucht neue Felder im
  Übergabeformat, und **ein unbekanntes Feld verwirft nach § 11 den ganzen Auftrag**. Die
  Feldliste gehört zuerst in die Papiere und ist im Übergabeformat festzulegen. Dabei
  ist § 8 zu beachten: Kosten dürfen auf der Gutschrift nicht als Minusposten erscheinen;
  ob eine erläuternde Anlage davon berührt ist, entscheidet dasselbe Papier. Das Speichern
  der bereits bekannten `herleitung` braucht dagegen **keine** Formatänderung.
- **Eine Vertragsnummer auf dem Beleg.** Das Übergabeformat führt keine; eine
  Vertragsnummer gilt zwischen den Parteien und gehört nicht auf diesen Beleg.
- **Korrektur eines finalisierten 389.** Heute ist ein Korrekturlauf beim Sender ein Ersatz
  des ganzen Laufs. Bis geklärt ist, was das für einen bereits gestellten Beleg bedeutet,
  ist der Stornoweg gesperrt (Umfang 7).
- **Ein Nachweis der Bemessungsgrundlage bei der manuellen Anlage.** Wer von Hand eine
  Honorargutschrift schreibt, verantwortet die Summe selbst; das Programm prüft sie gegen
  nichts. Die Rechenprobe greift nur, wenn eine `herleitung` eingegeben oder aus einem
  signierten Auftrag übernommen wurde.

## Offene Frage an das Übergabeformat

Der in § 8 zitierte Satz nennt **einen** Steuersatz, 7 %. Der Kleinunternehmerfall mit
Kategorie `E` und Satz 0 steht dort nicht, wird aber vom Code bereits behandelt
(`steuer_fuer` in `abrechnungsauftrag_wirkung.py`, Befreiungstext `EXEMPTION_SELF_BILLING_E`
in `zugferd_xml.py`). Ob das Format
die Ausnahme an anderer Stelle führt, ist von hier aus nicht entscheidbar. Die Frage ist im
Übergabeformat festzulegen, bevor der erste echte Beleg entsteht. Bis dahin gilt sie
als offen und nicht als stillschweigend vereinbart.
