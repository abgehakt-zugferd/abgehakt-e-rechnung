# Auftrag: Ausgangsrechnung aus einem Rechnungsauftrag und Abrechnungsaufstellung

**Status:** geplant, freigegeben am 2026-10-17; nach Gegenrede überarbeitet. Übergabeformat ab Fassung 1.7 (§§ 8a, 8b).

## Anlass

Viele Unternehmer verkaufen über Plattformen, die selbst einen Bericht über die Erlöse
liefern und danach auszahlen. Der Unternehmer kennt den Betrag also erst aus dem Bericht
und muss trotzdem eine Rechnung ausstellen, wenn der Auszahler in der EU sitzt
(Reverse Charge), oder eine Abrechnungsaufstellung für die Buchhaltung anlegen, wenn er
in einem Drittland sitzt und Quellensteuer einbehält.

Ein vorgelagertes System liest diese Berichte bereits und kann Abgehakt zwei neue,
signierte Aufträge schicken:

| Auftrag | Ergebnis in Abgehakt | Rechtsnatur |
|---|---|---|
| `rechnungsauftrag` | Entwurf einer Ausgangsrechnung (BT-3 380) | Rechnung nach § 14 UStG |
| `aufstellungsauftrag` | Entwurf einer Abrechnungsaufstellung mit zwei Anlagen | **keine** Rechnung |

Beide Wege enden in einem **Entwurf**. Finalisieren und Versenden bleiben Handgriffe des
Nutzers, wie bei jeder anderen Rechnung.

## Entscheidungen, die feststehen

1. **Entwurf, Beträge gebunden.** Aus einem Auftrag entsteht ein Entwurf. Beträge,
   Kunde, Leistungszeitraum und die Gliederung in Gruppen sind gebunden, weil sie aus dem
   signierten Auftrag stammen (`belegsperre.gilt` nach Herkunft, wie bei der 389).
   Bezeichnungen, Kopf- und Fußtext, Bemerkung und Belegsprache bleiben frei.
2. **Steuer aus dem Kundenstamm.** Der Auftrag trägt nur Netto. Steuerkategorie, Satz und
   Vermerk nimmt Abgehakt aus einer neuen Vorgabe am Kunden. Fehlt sie, entsteht kein
   Entwurf, und die Oberfläche sagt, was am Kunden fehlt (Muster: ungeklärter Steuerstatus
   bei der 389).
3. **Gruppen sind freier Text.** Abgehakt prüft nur die Form (alle oder keine,
   zusammenhängend, zeichengleich nach NFC), nie den Wortlaut. Im PDF bekommt jede Gruppe
   eine Überschrift und eine Zwischensumme. Die XML bleibt flach (EN 16931 kennt keine
   Zwischensummen); jede Position trägt ihre Gruppe als Positionsnotiz (BT-127).
4. **Zahlungshinweis statt Fälligkeit.** Zahlt der Kunde nach eigenem Takt, ist ein
   Fälligkeitsdatum eine Angabe, die nichts regelt. Der Kunde bekommt einen optionalen
   Zahlungshinweis. Ist er gesetzt, entfällt BT-9 in der XML, BT-20 trägt den Hinweis, und
   das PDF zeigt ihn statt des Fälligkeitsdatums. Die Ausstellungsfrist nach § 14a UStG
   bleibt davon unberührt.
5. **Kopf- und Fußtext je Kunde**, mit dem Platzhalter `{leistungsmonat}` (MM/JJJJ aus dem
   Leistungszeitraum). Dort stehen Vertragsgrundlage, der Hinweis auf den Bericht als
   Einzelaufstellung und der Reverse-Charge-Vermerk, so wie der Kunde ihn erwartet.
6. **Versand an Buchhaltung und Kunde haben getrennte Vermerke** (Entscheidung
   2026-10-17). Das gilt für jede Rechnung, nicht nur für Belege aus Aufträgen. Drei Wege:
   - **Kunde und Buchhaltung** (Standard, vorgewählt): Mail an den Kunden mit Blindkopie an
     die Upload-Adresse der Buchhaltung, wie bisher; setzt beide Vermerke.
   - **Nur Buchhaltung**: Mail nur an die Upload-Adresse; der Kunde bleibt offen.
   - **Zustellung an den Kunden vermerken**: keine Mail. Der Nutzer trägt Datum und Weg als
     Freitext ein (etwa „Upload in das Kundenportal“). Korrigiert wird durch einen neuen
     Eintrag, nicht durch Überschreiben; angezeigt wird der jüngste, alle bleiben im
     Versandprotokoll.
   Ein Beleg, der an die Buchhaltung, aber noch nicht an den Kunden ging, ist gestellt,
   dokumentiert und gilt als „nicht versendet“.
7. **Auftragsschlüssel.** Jeder Beleg aus einem Auftrag speichert dessen
   `auftragsschluessel`. Solange zu einem Schlüssel ein Beleg besteht, der weder storniert
   noch verworfen ist, lehnt Abgehakt einen neuen Auftrag mit `AUFTRAG_SCHON_GERECHNET` ab;
   `erhalten` nennt die Nummer oder „Entwurf“. Ein partieller Unique-Index in der
   Datenbank sichert dieselbe Zusage gegen zwei gleichzeitige Anfragen.
8. **Abrechnungsaufstellung ist ein eigenes Modell**, keine Belegart der Rechnung. Sie hat
   keine Steuer, keinen Typcode, keine XML und keinen Mustang-Lauf. Eigene Tabelle, eigener
   Nummernkreis mit eigenem Präfix, eigene Seiten. Finalisieren erzeugt ein PDF/A und sperrt
   den Datensatz wie eine gestellte Rechnung (Guard und Datenbank-Trigger).
9. **Anlagen.** Eine Aufstellung hat genau zwei xlsx-Anlagen. Abgehakt liest sie aus
   `anlagen/` neben dem Beleg, prüft Größe und SHA-256 und bewahrt beim Annehmen eine
   byte-gleiche Kopie unter `storage/uebergaben/<richtung>/anlagen/<sha256>.xlsx` auf. An
   die Buchhaltung geht **nur** das PDF der Aufstellung; es nennt Dateiname und SHA-256
   beider Anlagen. Die Anlagen stehen im GoBD-Export.
10. **Korrektur heißt stornieren und neu.** Eine gestellte Aufstellung lässt sich stornieren:
    Status `cancelled`, ein Storno-PDF „Stornierung der Abrechnungsaufstellung Nr. …“ geht
    auf demselben Weg an die Buchhaltung, der Auftragsschlüssel ist danach frei. Für die
    Ausgangsrechnung gilt der vorhandene Weg (Stornorechnung 381, dann neu).

## Festlegungen nach der Gegenrede (2026-10-17)

Eine Gegenrede hat den Plan gegen Format, Code und Steuerrecht gelesen. Daraus folgt:

11. **Negative Positionen.** Der Validator lehnt heute jeden negativen Einzelpreis ab
    (`ITEM_PRICE_NEGATIVE`). Bei einer 380 aus einem Rechnungsauftrag (`belegsperre.gilt`)
    ist eine negative Position zulässig; die Summe der Rechnung bleibt größer null. Ein Test
    bringt einen solchen Entwurf durch Validator und Mustang.
12. **Sperrender Schlüssel als eigene Spalte.** Eine Rechnung, die per Stornorechnung
    aufgehoben wurde, behält ihren Status (`issued` oder `paid`); der Status taugt deshalb
    nicht als Kriterium. Jeder Beleg aus einem Auftrag trägt zwei Spalten:
    `auftragsschluessel` (unveränderlich, der Nachweis) und `auftragsschluessel_offen`
    (dieselbe Zeichenkette, solange der Beleg sperrt, sonst NULL) mit Unique-Index.
    Geleert wird sie beim Verwerfen, beim Finalisieren der Stornorechnung zum Original,
    beim manuellen Stornieren und beim Storno der Aufstellung. Nach dem Finalisieren darf
    die Spalte nur geleert, nie gesetzt oder geändert werden (Guard, Muster
    `datev_sent_at`). Die Abfrage des Lesers fragt beide Tabellen (Rechnung und
    Aufstellung), denn das Format spricht von „einem Dokument“.
13. **Steuervorgabe.** Am Kunden steht `auftrag_steuer` mit dem Wertevorrat `{"AE"}` in
    dieser Fassung. Ein Entwurf entsteht nur, wenn der Kunde eine USt-IdNr. trägt. Den
    Reverse-Charge-Vermerk druckt weiter das System (`AE_HINWEIS`, BT-120); er gehört nicht
    in den Kundenfußtext. Die Steuerkategorie ist am Auftragsentwurf gebunden.
14. **Ausstellungsdatum beim Finalisieren.** Ein Entwurf aus einem Auftrag erhält sein
    `issue_date` erst beim Finalisieren (heute in Europe/Berlin). Der Validator warnt
    (`AUSSTELLUNGSFRIST_14A`), wenn das Ausstellungsdatum nach dem 15. des Monats liegt,
    der auf das Ende des Leistungszeitraums folgt (§ 14a Abs. 1 Satz 2 UStG).
15. **Kundenvorgaben werden kopiert, nicht gelesen.** Kopf- und Fußtext (Platzhalter
    schon ersetzt) stehen als eigene Spalten an der Rechnung, der Zahlungshinweis in
    `payment_terms`. Eine spätere Änderung am Kunden ändert keinen bestehenden Beleg.
    Invariante als CHECK: `due_date IS NOT NULL OR payment_terms IS NOT NULL` (BR-CO-25).
    Betroffen von `due_date IS NULL` sind PDF, XML (BT-9 entfällt), das Bearbeiten-Formular
    und die Kennzahlen: ein Beleg ohne Fälligkeit ist nie überfällig, das steht in
    `uebersicht-kennzahlen.md`.
16. **Versand an die Buchhaltung.** Empfänger ist die Upload-Adresse, keine Blindkopie,
    eine neutrale Mailschablone ohne Anrede des Kunden. Das Versandprotokoll trägt das Ziel
    (`buchhaltung` oder `kunde`) in einer eigenen Spalte. Die Kennzahl und der Listenfilter
    „nicht versendet“ beziehen sich auf den Kunden.
17. **Storno der Aufstellung ist eine eigene Zeile** mit eigener Nummer und Verweis auf
    das Original, wie bei Rechnungen; das Original wird `cancelled`. Damit laufen Nummer,
    Sperre, Versand, Export und Schlüsselfreigabe über denselben Weg.
18. **Nummer beim Entwurf**, wie bei Rechnungen; ein verworfener Entwurf heißt
    `discarded` und erklärt die Lücke.
19. **Zurückholen und Wettlauf.** Das Zurückholen eines verworfenen Auftragsentwurfs
    prüft, ob der Schlüssel inzwischen belegt ist. Ein Index-Treffer bei zwei
    gleichzeitigen Annahmen wird zum Befund `AUFTRAG_SCHON_GERECHNET`, nicht zu HTTP 500.
20. **Leserdetails.** `aufstellungsauftrag.leistungszeitraum` ist wie in § 8a genau ein
    Kalendermonat. `anlagen: []` ist `WERT_UNBRAUCHBAR` (genau zwei), nicht
    `PFLICHTFELD_FEHLT`. Die Formprüfung kennt die Geldfelder beider Nutzlasten; `kurs` ist
    weder Geld noch Satz. Die Empfangslage des Lesers bekommt
    `dokument_zu_auftragsschluessel(schluessel) -> Optional[str]` schon im ersten
    Schritt; die Vektoren laufen mit einer Testlage.
21. **Inhalt des Aufstellungs-PDF.** Kunde, Leistungsmonat, Zahlungsnummer und
    -datum; in Berichtswährung Brutto, Quellensteuer, Netto; in Euro der gedruckte Kurs und
    der Zahlbetrag; beide Anlagen mit Dateiname, Größe und SHA-256; der Satz „Keine
    Rechnung im Sinne des § 14 UStG“. Abgehakt rechnet keinen Wert in Euro um. Die Form gilt
    als vorläufig, bis die Steuerberatung sie gesehen hat (wie der Storno-Code der 389).
22. **GoBD-Export der Anlagen.** Die Aufstellung speichert beide Hashes; der Export nimmt
    die Anlagen aller Aufstellungen des Zeitraums, eine geteilte Datei einmal, fehlende in
    `fehlende_dateien.txt`.
23. **Kennzahlen.** Aufstellungen zählen in dieser Fassung nicht in Umsatz und
    Steuerkennzahlen; das steht ausdrücklich in `uebersicht-kennzahlen.md`.

## Der Leser (beide Arten)

Beide Arten kommen in `LESBARE_ARTEN`. Die Prüfreihenfolge folgt § 11 und § 8b: Felder,
dann Werte und Summen, dann Dateien. Jeder Befund trägt einen Code aus der geschlossenen
Liste und einen Pfad.

`rechnungsauftrag` (§ 8a): `typcode` nur `"380"`; `waehrung` nur `"EUR"`;
`leistungszeitraum` genau ein Kalendermonat; `summe.netto == Σ positionen.netto` und
`> 0.00` (`SUMME_STIMMT_NICHT`); einzelne Positionen dürfen negativ sein, `"0.00"` nicht;
Gruppenregeln wie oben; keine zwei Positionen mit gleicher Bezeichnung;
`Σ grundlagen.netto == summe.netto`; `grundlagen[].quelle` nur `"abrechnungsbericht"`;
`anlagen` ist `UNBEKANNTES_FELD`; `auftragsschluessel` `[a-z0-9:-]{1,128}`.

`aufstellungsauftrag` (§ 8b): kein `typcode`, keine Steuerfelder; `waehrung` drei
Großbuchstaben; `brutto − quellensteuer == netto` exakt; `quellensteuer ≥ 0`;
`netto > 0.00`; `umrechnung` genau dann, wenn `waehrung ≠ "EUR"`, mit `kurs` als
Zeichenkette und `umrechnung.waehrung` nur `"EUR"`; die Gleichung Netto × Kurs wird
**nicht** geprüft; `zahlung.zahlungsnummer` `^[0-9]+$`; `anlagen` genau zwei, je eine
`quelle` aus `{"abrechnungsbericht", "zahlungsbericht"}`, `groesse ≤ 20 000 000`,
`medientyp` nur xlsx; danach die Dateien: fehlt eine, `ANLAGE_FEHLT`, weichen Hash oder
Größe ab, `ANLAGE_HASH_FALSCH`.

Abnahme des Lesers sind die Vektorgruppen `rechnungsauftraege/` und `aufstellungen/` des
Formats: jeder Vektor trägt genau einen erwarteten Befund oder wird angenommen.

## Bauschritte

Jeder Schritt ist ein eigener, testgetriebener Auftrag mit voller Suite und eingehängten
Formatvektoren.

1. **Leser § 8a** samt Vektorgruppe `rechnungsauftraege/` und
   `dokument_zu_auftragsschluessel` in der Empfangslage (Testlage).
2. **Kundenvorgaben und Fälligkeit**: `auftrag_steuer`, Kopf- und Fußtext, Zahlungshinweis,
   Belegsprache; Kopie an die Rechnung; `due_date`
   nullable mit CHECK und allen betroffenen Stellen.
3. **Positionsgruppen**: Spalte an der Position, PDF mit Überschrift und Zwischensumme,
   BT-127 in der XML, Bindung über die Belegsperre; negative Positionen bei Auftragsentwürfen.
4. **Wirkung § 8a**: Entwurf 380, beide Schlüsselspalten mit Index und Freigabe,
   `AUFTRAG_SCHON_GERECHNET` aus der Datenbank, Zurückholen, Wettlauf,
   Ausstellungsdatum beim Finalisieren, Warnung § 14a.
5. **Versand entkoppeln**: Buchhaltung und Kunde als zwei Schritte mit eigenen Vermerken,
   Protokollspalte, Schablone, Kennzahl und Filter; Migration für den Bestand (bisheriger
   Erstversand gilt für beide).
6. **Leser § 8b** samt Anlagenprüfung und Vektorgruppe `aufstellungen/`.
7. **Abrechnungsaufstellung**, in sieben Teilen:
   a) Modell, Migration, Guard, Trigger, Audit, zweiter Nummernkreis;
   b) Wirkung (Entwurf) und Anlagenkopie;
   c) PDF/A und Finalisieren;
   d) Versand an die Buchhaltung über den entkoppelten Schritt aus 5;
   e) Storno als eigene Zeile;
   f) GoBD-Export und Archivansicht;
   g) Liste und Detailseite.

## Nicht in diesem Auftrag

- Fremdwährung im `rechnungsauftrag` (Fassung 1.x kennt nur EUR).
- Eine Prüfung des Umrechnungskurses.
- Ein Ersatz für die Stornorechnung bei Aufträgen; es gilt der vorhandene Weg.
