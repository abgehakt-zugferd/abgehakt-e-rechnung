# Auftrag: Kennzahlen nach Storno per Gutschrift (Issue #141)

Stand: 08.10.2026. Spezifikation fuer einen test-first auszufuehrenden Auftrag.

## Anlass

`backend/app/services/dashboard_kennzahlen.py` bildet eine Stornierung per Gutschrift nicht
konsistent ab. Die Belege sind korrekt, die Summen der Uebersicht nicht. Nach einem Storno
stimmen heute nie offene Forderungen und Umsatz zugleich (Issue #141, drei Rechenbeispiele).

## Grundsatz

**Eine Stornierung wirkt in jeder Kennzahl genau einmal.** Wirksam storniert ist eine Rechnung,
zu der eine Gutschrift (381) mit Status `issued` oder `paid` besteht. Ein Gutschrift-Entwurf,
eine verworfene oder eine selbst auf `cancelled` gesetzte Gutschrift wirkt nicht.

Eine Gutschrift gehoert in denselben Topf wie ihr Original: was das Original nicht zaehlt, mindert
auch die Gutschrift nicht.

Grundlage: Eine Gutschrift spiegelt ihr Original immer vollstaendig (`STORNO_AMOUNT_MISMATCH` im
Validator, `build_storno` kopiert die Summen). Eine wirksame Gutschrift hebt das Original also
ganz auf, nie teilweise. Gegenprobe der Bestandsdaten am 08.10.2026: keine Gutschrift mit Original
und keinerlei Beleg vom Typ Gutschrift oder Honorargutschrift im Bestand.

Diese Grundlage ist eine Grenze, die nicht aufgeweicht werden darf, ohne die Kennzahlen mitzuziehen.
Ein Teilstorno (etwa "80 % bei Ruecktritt") laeuft deshalb als volle Gutschrift plus neue Rechnung
ueber den verbleibenden Teil (Stornogebuehr), nicht als Teilgutschrift. Ob eine Stornogebuehr
umsatzsteuerpflichtiges Entgelt oder echter Schadensersatz ist, klaert die Steuerberatung.

## Regeln je Kennzahl

| Kennzahl | heute | neu |
|---|---|---|
| `offene_forderungen`, `ueberfaellige_forderungen` | Standardrechnung, `issued` | dazu: **nicht wirksam storniert** |
| `schuldige_umsatzsteuer`, `nettoumsatz_ytd` (Original) | Standardrechnung, `issued`/`paid` | Standardrechnung, `issued`/`paid`, **oder `cancelled` und wirksam storniert** |
| dieselben (Abzug Gutschrift) | jede gestellte 381 | gestellte 381, deren Original eine **Standardrechnung** ist, oder **ohne Original** (Altbestand) |
| `vorsteuer_honorargutschriften` | gestellte 389 | dazu: **abzueglich** gestellter 381, deren Original eine 389 ist |
| 381 zu einer 386 | wird vom Umsatz abgezogen | wird **nirgends** abgezogen, weil die 386 nirgends zaehlt |

Zum zweiten Punkt: Wer das Original nach dem Storno von Hand auf `cancelled` setzt, nimmt es heute
aus dem Umsatz, waehrend die Gutschrift weiter abgezogen wird. Neu zaehlt ein solches Original im
Zeitraum seiner Ausstellung, die Gutschrift im Zeitraum ihrer Ausstellung. Ein `cancelled` ohne
wirksame Gutschrift bleibt wie heute draussen (Status ohne Gegenbeleg, Knopf "Als storniert
markieren").

Die Gutschrift wird nach ihrem eigenen Ausstellungsdatum gezaehlt, nicht nach dem des Originals.
Liegen beide in verschiedenen Zeitraeumen, zeigt die Uebersicht im ersten Zeitraum das Original,
im zweiten die Minderung. Das bildet die Belege ab; ob es die steuerliche Periodisierung trifft,
ist eine Frage an die Steuerberatung (Issue #141, Abgrenzung).

## Schnitt

Die oeffentlichen Funktionen in `dashboard_kennzahlen.py` behalten Namen und Signatur; `main.py`
aendert sich nicht. Die Regel steht an einer Stelle, im Modul `services/storno_wirkung.py`:

- `WIRKSAM_STORNIERT`: SQL-Bedingung (EXISTS) an `Invoice` fuer "zu dieser Rechnung besteht eine
  gestellte oder ausgezahlte Gutschrift". Eine Quelle fuer Kennzahlen und Rechnungsliste.
- `summe_gutschriften(db, feld, seit, *, topf, bis, ausgezahlt)`: summiert gestellte 381 nach dem
  Typ ihres Originals (`None` fuer die Standardrechnung samt Altbestand ohne Original,
  `self_billing`); mit `ausgezahlt` nur Rueckzahlungen zu bezahlten Originalen nach `bezahlt_am`.

**Kachel und Liste** (`docs/specs/uebersicht-kennzahlen.md`: beide zeigen dieselbe Zahl): Die
Rechnungsliste kennt den Filter `storno=ohne` mit derselben Bedingung. Die Kacheln "Offene
Forderungen" und "Ueberfaellig" verlinken mit `storno=ohne`. Der Filter ist wie die anderen
sichtbar, aufhebbar und bleibt beim Blaettern erhalten.

## Ist-Umsatz (nach Gegenpruefung)

`umsatz_im_zeitraum` zaehlt bezahlte Standardrechnungen nach `bezahlt_am` (Entscheidung vom
2026-09-30: Umsatz ist, was bezahlt wurde). Eine Gutschrift mit Status `paid` ist die Auszahlung
an den Kunden und traegt ihr eigenes `bezahlt_am`. Neu zieht `umsatz_im_zeitraum` solche
ausgezahlten Gutschriften nach ihrem `bezahlt_am` ab, aber nur, wenn ihr Original eine bezahlte
Standardrechnung ist: nur dann ist Geld hereingekommen, das zurueckgeht. Eine ausgezahlte
Gutschrift ohne Original laesst den Ist-Umsatz unberuehrt (Bestandstest zu #5). Eine gestellte,
noch nicht ausgezahlte Gutschrift mindert den Ist-Umsatz nicht: das Geld ist noch da.

`bezahlt_im_zeitraum` bleibt der Geldeingang brutto. Eine Rueckzahlung ist ein Geldausgang; ihn
dort abzuziehen, ergaebe im Monat der Rueckzahlung eine negative Zahl unter "Bezahlt diesen Monat".

## Nicht Teil dieses Auftrags

- `nicht_versendet_anzahl`: ein storniertes, nie versendetes Original zaehlt als "nicht versendet",
  die Gutschrift dazu gar nicht. Versand ist eine eigene Frage.
- Waehrungen werden weiter ohne Umrechnung addiert (bestehende Vereinfachung).

## Abnahme

Integrationstests mit `pg_session` und festen Sollwerten:

1. Rechnung 119,00 gestellt, Gutschrift gestellt: offen 0,00; ueberfaellig 0,00.
2. Wie 1., Gutschrift nur Entwurf: offen 119,00.
3. Rechnung 100,00 netto, Gutschrift gestellt, Original von Hand `cancelled`: Nettoumsatz 0,00,
   USt 0,00.
4. `cancelled` ohne Gutschrift: zaehlt nicht (Bestand bleibt gruen).
5. 386 mit gestellter Gutschrift: Nettoumsatz und USt 0,00.
6. 389 mit gestellter Gutschrift: Vorsteuer 0,00; USt unberuehrt.
7. Gutschrift ohne Original (Altbestand, bestehende Tests): wird weiter abgezogen.
8. Original und Gutschrift in verschiedenen Quartalen: Quartals-USt zeigt jeweils nur den eigenen
   Beleg.
9. Gutschrift mit Status `paid` (ausgezahlt) wirkt wie `issued`: offen 0,00.
10. Original bezahlt, Gutschrift ausgezahlt: Ist-Umsatz des Jahres 0,00; vor der Auszahlung 100,00.

## Gegenpruefung (08.10.2026)

Vibe (`mistral-medium-3.5`) hat sieben Befunde geliefert, Cursor und Codex hatten kein Kontingent.
Uebernommen: Ist-Umsatz nach Auszahlung (oben), Abnahmefall 9. Verworfen: "cancelled-Original
zaehlt nicht" (braechte das Minus aus #141 zurueck; das Programm selbst raet nach einem Storno,
das Original auf storniert zu setzen, `bezahlt_am.py`), "Bestandstest widerspricht" (eine
Gutschrift ohne Original hebt keine Rechnung auf). Zwei Befunde wiederholten bekannte Punkte.

Zweite Gegenpruefung durch Fable auf dem fertigen Diff, zehn Befunde. Uebernommen: Kachel und Liste
(oben), drei Testluecken mit benannter Mutation (Ist-Umsatz nach Auszahlungsmonat, stornierte
Gutschrift in der USt, Auszahlung ohne Zahlungseingang), doppelte Topfbedingung entfernt, Warnung
zur Alias-Korrelation, dieser Abschnitt "Schnitt". Offen und eigener Auftrag: `bezahlt_am` und
`create_storno` verstehen unter "Gutschrift zum Original" alles ausser `discarded`, die Kennzahlen
nur `issued`/`paid`; eine selbst stornierte Gutschrift laesst das Original danach dauerhaft offen,
weder bezahlbar noch erneut stornierbar. Offen fuer den Betreiber: einmalige Gegenprobe der
Bestandsdaten auf Gutschriften mit Original und abweichendem Betrag (zwischen 11.08. und 23.08.2026
waren sie technisch moeglich).
