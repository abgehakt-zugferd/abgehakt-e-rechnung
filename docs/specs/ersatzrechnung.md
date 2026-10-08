# Auftrag: Ersatzrechnung zu einer stornierten Rechnung

Stand: 08.10.2026. Spezifikation fuer einen test-first auszufuehrenden Auftrag.

## Anlass

Eine gestellte Rechnung hatte einen falschen Empfaenger (Name, Anschrift, falsche Firma).
Korrigiert wird in diesem Programm ausschliesslich per Gutschrift (381) und neuer Rechnung.
Die neue Rechnung traegt heute keinen maschinenlesbaren Bezug auf die stornierte. Die Software
des Empfaengers sieht zwei unabhaengige Rechnungen ueber dieselbe Leistung; den Zusammenhang
kennt nur, wer die Bemerkungen liest.

Rechtlich genuegt nach § 31 Abs. 5 UStDV ein Dokument, das spezifisch und eindeutig auf die
Ursprungsrechnung verweist. Die Gutschrift bleibt trotzdem Pflicht in diesem Programm: sie ist der
Gegenbeleg, der Forderung und ausgewiesene Steuer der falschen Rechnung in den eigenen Belegen
mindert, unabhaengig davon, ob gezahlt wurde. Ob und wann die Steuer damit tatsaechlich
berichtigt ist, haengt an weiteren Voraussetzungen (§ 14c, § 17 UStG) und ist eine Frage an die
Steuerberatung, keine Zusage dieses Programms.

## Ergebnis

Eine **Ersatzrechnung** ist eine gewoehnliche Rechnung (380, oder 386 als Anzahlungsrechnung),
die auf genau eine stornierte Rechnung verweist. Erfolg heisst:

1. **XML:** BT-25 (Nummer) und BT-26 (Datum) der ersetzten Rechnung in
   `ram:InvoiceReferencedDocument`, Belegart bleibt 380 bzw. 386.
2. **PDF:** feste Zeile aus dem Bezug selbst, nicht aus den Bemerkungen:
   `Ersetzt Rechnung {nummer} vom {datum}.` bzw. `Replaces invoice {nummer} dated {datum}.`
   nach Belegsprache der Ersatzrechnung.
3. **GoBD-Export:** Spalte `ersetzt_rechnungsnummer` in `rechnungen.csv` und `index.xml`.

Nicht Teil dieses Auftrags: ein Knopf, der Gutschrift und Ersatz in einem Schritt anlegt.
Belegart 384 bleibt systemreserviert und wird hier nicht benutzt.

## Entscheidungen (Auftraggeber, 08.10.2026)

| Frage | Entscheidung |
|---|---|
| Wann darf eine Ersatzrechnung entstehen? | Anlegen erst, wenn zum Original eine nicht verworfene Gutschrift existiert. Finalisieren erst, wenn diese Gutschrift gestellt ist (`issued` oder `paid`). |
| Wie viele pro Original? | Hoechstens eine nicht verworfene. Ist die Ersatzrechnung selbst falsch, wird sie storniert und ihrerseits ersetzt: eine Kette. |
| Empfaenger? | Frei waehlbar. Vorbelegt mit dem Kunden des Originals. |

## Datenmodell

Neue Spalte `invoices.ersetzt_invoice_id` (UUID, FK auf `invoices.id`, nullable, Index).
**Nicht** `original_invoice_id` mitbenutzen: diese Spalte gehoert den Folgebelegen (381, 384,
389), der Validator verbietet sie bei 380/386 (`ORIGINAL_INVOICE_NOT_ALLOWED`), und der Index
`uq_invoices_eine_aktive_gutschrift_pro_original` erlaubt pro Original nur einen Beleg.

Partieller eindeutiger Index `uq_invoices_eine_aktive_ersatzrechnung_pro_original` auf
`ersetzt_invoice_id` mit `status <> 'discarded' AND ersetzt_invoice_id IS NOT NULL`. Migration 022,
dieselbe Quelle wie `create_all` (alembic check).

Unveraenderlichkeit nach dem Finalisieren ergibt sich aus `MUTABLE_AFTER_FINALIZE` (Positivliste)
ohne Aenderung am Waechter. Ein Test belegt das.

## Fachmodul `services/ersatzrechnung.py`

Eine Frage, eine Antwort:

```python
def pruefe_ersetzbar(db, original_id, *, ausser=None) -> Invoice
```

Liefert das Original oder wirft `ErsatzNichtMoeglich` mit Code und lesbarem Text:

| Code | Lage |
|---|---|
| `ERSATZ_ORIGINAL_UNBEKANNT` | Kennung ungueltig oder nicht gefunden |
| `ERSATZ_ORIGINAL_KEINE_RECHNUNG` | Original ist selbst ein Folgebeleg (381, 384, 389) oder Entwurf/verworfen |
| `ERSATZ_OHNE_GUTSCHRIFT` | keine nicht verworfene Gutschrift zum Original |
| `ERSATZ_SCHON_VORHANDEN` | es gibt schon eine nicht verworfene Ersatzrechnung (`ausser` nimmt den eigenen Entwurf aus) |

Dazu fuer den Validator:

```python
def pruefe_finalisierbar(invoice) -> list[Issue]
```

`ERSATZ_GUTSCHRIFT_NICHT_GESTELLT` (Fehler), solange die Gutschrift zum ersetzten Original nicht
`issued` oder `paid` ist. Damit steht in diesem Programm nie eine Ersatzrechnung neben einem
ungeminderten Original. Das ist eine Aussage ueber die eigenen Belege, nicht ueber den Zugang der
Gutschrift beim Empfaenger und nicht ueber die steuerliche Wirkung (siehe Grenzen).

`ERSATZ_DOPPELTER_BEZUG` (Fehler), wenn `original_invoice_id` und `ersetzt_invoice_id` zugleich
gesetzt sind. `_reference_xml` kann nur einen BT-25 schreiben.

Verbindlich ist die Pruefung beim Finalisieren. Die Pruefung beim Anlegen ist die freundliche
Antwort davor: wird die Gutschrift zwischen Anlegen und Finalisieren verworfen, bleibt ein
Ersatz-Entwurf stehen, der nicht finalisierbar ist. Das ist gewollt und kein Wettlauf-Schaden.

## Ablauf

1. Detailseite einer gestellten Rechnung mit Gutschrift und ohne Ersatz: Knopf
   **Ersatzrechnung anlegen** fuehrt auf `GET /invoices/neu?ersetzt=<id>`.
2. `GET /neu?ersetzt=<id>` belegt das Formular wie `?vorlage=<id>` vor (`docs/specs/kopieren.md`),
   zeigt einen Hinweisbalken mit Nummer des Originals und traegt ein verstecktes Feld
   `ersetzt_invoice_id`. Unbrauchbare Kennung: Fehler sichtbar, Status 404 bzw. 400.
   **Abweichung vom Kopiervertrag:** die Belegart (380 oder 386) wird vorbelegt. Beim Kopieren
   ist ein still geerbter Typ die Gefahr; beim Ersatz ist ein still verlorener Typ die Gefahr,
   denn aus der Korrektur einer Anzahlungsrechnung wuerde sonst eine Standardrechnung.
3. `POST /neu` mit `ersetzt_invoice_id`: `pruefe_ersetzbar` **vor** der Nummernvergabe. Eine
   Ablehnung erhoeht weder den Zaehler noch legt sie eine Zeile an. Ein Wettlauf am Index endet
   mit Rollback und derselben Meldung wie die Vorabpruefung.
4. `POST /{id}/bearbeiten` laesst den Bezug unveraendert; ein mitgesendetes Feld wird abgelehnt.
5. Kopieren (`?vorlage=`) uebernimmt `ersetzt_invoice_id` nie (Feldvertrag kopieren.md).
6. `POST /{id}/zurueckholen` eines verworfenen Ersatz-Entwurfs prueft erneut mit
   `pruefe_ersetzbar` (der eigene Entwurf zaehlt nicht mit). Gibt es inzwischen einen anderen
   Ersatz, antwortet es 400 mit `ERSATZ_SCHON_VORHANDEN` statt am Index mit 500.
7. `POST /{id}/status` auf `cancelled` fuer eine Gutschrift wird abgelehnt
   (`ERSATZ_GUTSCHRIFT_GEBUNDEN`), solange zu ihrem Original eine nicht verworfene Ersatzrechnung
   besteht. Sonst lebte das Original neben seinem Ersatz wieder auf.

## Naht fuer den Durchstich

`POST /invoices/neu` mit `ersetzt_invoice_id`, dann Finalisieren, dann BT-25 im gespeicherten XML.
Integrationstest mit `pg_session`.

## Grenzen und Fremdbefunde (Gegenpruefung 08.10.2026)

Eine Gegenpruefung durch ein zweites Modell hat zwoelf Befunde geliefert. Eingearbeitet sind
oben: Ketteninvariante der Gutschrift (Ablauf 7), Zurueckholen (Ablauf 6), doppelter Bezug,
Belegart beim Ersatz einer 386, verbindliche Pruefung beim Finalisieren. Migration 022 ist noch
auf keiner Installation angewendet; der Unique-Index kommt deshalb in dieselbe Revision.

Nicht Teil dieses Auftrags, weil schon ohne Ersatzrechnung vorhanden:

- **Kennzahlen nach Storno.** `offene_forderungen` zaehlt ein storniertes Original weiter als
  offen, die Gutschrift mindert es dort nicht. Setzt man das Original von Hand auf `cancelled`,
  zieht der Umsatz die Gutschrift trotzdem ab. Gutschriften auf eine 386 werden abgezogen, die
  386 selbst aber nicht gezaehlt. Eigener Auftrag.
- **Zeitraumexport.** Original oder Gutschrift koennen ausserhalb des exportierten Zeitraums
  liegen; das gilt fuer `original_rechnungsnummer` genauso wie fuer die neue Spalte.

Fragen an die Steuerberatung, nicht an den Code:

- Bereits bezahltes Original: Verrechnung der Zahlung mit dem Ersatz, Rueckzahlung oder neue
  Zahlung. Das Programm uebertraegt keine Zahlung.
- Periodisierung, wenn Gutschrift und Ersatz in verschiedenen Voranmeldungszeitraeumen liegen.
- Nachweis, dass die Gutschrift dem bisherigen Empfaenger zugegangen ist. Ein Versandversuch
  per Mail oder DATEV ist kein Zugangsnachweis.
- XRechnung (BR-DE-17) kennt 386 nicht; fuer ZUGFeRD EN16931 gilt das nicht. BT-25 bei 380
  verletzt keine EN16931-Regel (BR-55 verlangt nur die Nummer). Wie DATEV einen 380 mit BT-25
  verbucht, ist nicht gemessen.

## Offene Punkte

- Detailseite des Originals zeigt `ersetzt durch ...` mit Link: gewuenscht, aber nicht Teil der
  Erfolgskriterien.
