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
ganz auf, nie teilweise.

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
ist eine Frage an die Steuerberatung (siehe `docs/specs/ersatzrechnung.md`, Grenzen).

## Schnitt

Die oeffentlichen Funktionen behalten Namen und Signatur; `main.py` aendert sich nicht.
Neu ist eine Stelle, die beide Fragen beantwortet, statt sie in jeder Funktion neu zu formulieren:

- `_wirksam_storniert()`: SQL-Bedingung (EXISTS) fuer "zu dieser Rechnung besteht eine
  gestellte Gutschrift". Eine Quelle fuer alle Kennzahlen.
- `_summe_gutschriften(db, feld, von, bis, *, topf)`: summiert gestellte 381 nach dem Typ ihres
  Originals (`standard`, `self_billing`).

## Nicht Teil dieses Auftrags

- `umsatz_im_zeitraum` und `bezahlt_im_zeitraum` (Geldeingang nach `bezahlt_am`): eine bezahlte,
  danach stornierte Rechnung zaehlt dort weiter. Die Rueckzahlung kennt das Programm nicht; das
  ist die offene Frage "bereits bezahltes Original" an die Steuerberatung.
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
