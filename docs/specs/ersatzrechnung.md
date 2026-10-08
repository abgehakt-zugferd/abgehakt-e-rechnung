# Auftrag: Ersatzrechnung zu einer stornierten Rechnung

Stand: 08.10.2026. Spezifikation fuer einen test-first auszufuehrenden Auftrag.

## Anlass

Eine gestellte Rechnung hatte einen falschen Empfaenger (Name, Anschrift, falsche Firma).
Korrigiert wird in diesem Programm ausschliesslich per Gutschrift (381) und neuer Rechnung.
Die neue Rechnung traegt heute keinen maschinenlesbaren Bezug auf die stornierte. Die Software
des Empfaengers sieht zwei unabhaengige Rechnungen ueber dieselbe Leistung; den Zusammenhang
kennt nur, wer die Bemerkungen liest.

Rechtlich genuegt nach § 31 Abs. 5 UStDV ein Dokument, das spezifisch und eindeutig auf die
Ursprungsrechnung verweist. Die Gutschrift bleibt trotzdem Pflicht in diesem Programm: sie hebt
Forderung und Umsatzsteuer der falschen Rechnung in den Buechern auf, unabhaengig davon, ob
gezahlt wurde.

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
`issued` oder `paid` ist. Damit sind nie zwei gueltige Rechnungen ueber dieselbe Leistung im Umlauf.

## Ablauf

1. Detailseite einer gestellten Rechnung mit Gutschrift und ohne Ersatz: Knopf
   **Ersatzrechnung anlegen** fuehrt auf `GET /invoices/neu?ersetzt=<id>`.
2. `GET /neu?ersetzt=<id>` belegt das Formular wie `?vorlage=<id>` vor (`docs/specs/kopieren.md`),
   zeigt einen Hinweisbalken mit Nummer des Originals und traegt ein verstecktes Feld
   `ersetzt_invoice_id`. Unbrauchbare Kennung: Fehler sichtbar, Status 404 bzw. 400.
3. `POST /neu` mit `ersetzt_invoice_id`: `pruefe_ersetzbar` **vor** der Nummernvergabe. Eine
   Ablehnung erhoeht weder den Zaehler noch legt sie eine Zeile an. Ein Wettlauf am Index endet
   mit Rollback und derselben Meldung wie die Vorabpruefung.
4. `POST /{id}/bearbeiten` laesst den Bezug unveraendert; ein mitgesendetes Feld wird abgelehnt.
5. Kopieren (`?vorlage=`) uebernimmt `ersetzt_invoice_id` nie (Feldvertrag kopieren.md).

## Naht fuer den Durchstich

`POST /invoices/neu` mit `ersetzt_invoice_id`, dann Finalisieren, dann BT-25 im gespeicherten XML.
Integrationstest mit `pg_session`.

## Offene Punkte

- Detailseite des Originals zeigt `ersetzt durch ...` mit Link: gewuenscht, aber nicht Teil der
  Erfolgskriterien.
