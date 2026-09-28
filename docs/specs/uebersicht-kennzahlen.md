# Auftrag: Kennzahlen der Uebersicht vertiefen

Stand: 28.09.2026. Spezifikation fuer einen getrennten, test-first auszufuehrenden Auftrag.
Keine Implementierung in dieser Datei. Bestand aus dem Repository wird vorausgesetzt.

## Anlass

Die Uebersicht zeigt sechs Kacheln mit je einer nackten Zahl. "Offene Rechnungen: 2" sagt
nicht, um wie viel Geld es geht, und nicht, ob davon etwas ueberfaellig ist. Das Feld
`invoices.due_date` wird in der gesamten Oberflaeche nirgends ausgewertet, obwohl es auf
jedem Beleg steht. Ebenso wird `datev_sent_at` nur auf der Detailseite gelesen: eine
finalisierte Rechnung, die nie beim Kunden ankam, ist auf der Uebersicht unsichtbar.

`draft_count` wird in `main.py:282` berechnet, an das Template gereicht und dort **nirgends
angezeigt**. Die vorhandene Berechnung ist also schon da, nur die Darstellung fehlt.

## Ergebnis und fachlicher Umfang

Die Uebersicht bekommt **eine** neue Kachel und ansonsten Unterzeilen an den bestehenden.
Kein zwoelfteiliges Raster. Jede Zahl, hinter der eine Belegmenge steht, ist ein Link in die
Rechnungsliste mit genau dieser Auswahl.

| Kachel | heute | danach zusaetzlich |
|---|---|---|
| Rechnungen gesamt | Anzahl | Unterzeile mit Entwuerfe / gestellt / bezahlt / storniert, jede Zahl verlinkt |
| Offene Rechnungen | Anzahl | offener Betrag brutto; die Kachel selbst verlinkt |
| **Ueberfaellig** (neu) | | Anzahl, Betrag, aeltester Beleg in Tagen; verlinkt |
| Bezahlt diesen Monat | Betrag | Vormonat als Vergleichszeile |
| Umsatz lfd. Jahr | Betrag | Vorjahr zum selben Stichtag mit Abweichung in Prozent |
| Schuldige Umsatzsteuer | Betrag lfd. Jahr | laufendes Quartal als Unterzeile |
| Gesch. Steuerabgaben | Betrag | unveraendert |

Dazu ein **Hinweisstreifen** ueber den Kacheln, der nur erscheint, wenn es finalisierte
Rechnungen ohne Versand gibt. Kein Dauerelement: ohne solche Belege ist das Markup nicht da.

**Ausdruecklich nicht in diesem Auftrag:** Top-Kunden, Klumpenrisiko, die Zwoelfmonatskurve,
durchschnittliche Zahlungsdauer, durchschnittlicher Rechnungsbetrag. Alle vier sind machbar
und wurden bewusst zurueckgestellt.

## Naht und Vertrag

Die Fachlogik gehoert in `backend/app/services/dashboard_kennzahlen.py`. Das Modul traegt
heute schon Umsatzsteuer und Ruecklage; es ist der vorhandene Ort fuer Kennzahlen und hat
keine Abhaengigkeit auf HTTP, Jinja oder Request. Diese Freiheit bleibt erhalten.

`main.dashboard` bleibt duenn: Zeitraeume bilden, Modulfunktionen rufen, Kontext fuellen. Es
entsteht **keine** neue Aggregationsabfrage direkt im Router. Die vier heute dort inline
gebauten Abfragen (`total_invoices`, `open_invoices`, `draft_count`, `paid_this_month`,
`revenue_ytd`) wandern mit in das Modul; das ist die Aufraeumarbeit, die zu diesem Auftrag
gehoert, und keine darueber hinausgehende Umstrukturierung.

Vorgesehene Schnittstelle, als Spezifikation und nicht als auszufuehrender Code:

- `belegzaehlung(db) -> Belegzaehlung` mit `gesamt`, `entwurf`, `gestellt`, `bezahlt`,
  `storniert`. `verworfen` wird gezaehlt, aber in `gesamt` mitgefuehrt wie bisher.
- `offene_forderungen(db) -> OffenePosten` mit `anzahl` und `betrag` (brutto).
- `ueberfaellige_forderungen(db, heute: date) -> Ueberfaellig` mit `anzahl`, `betrag`,
  `aeltester_tage: int | None`.
- `nicht_versendet_anzahl(db) -> int`.
- `bezahlt_im_zeitraum(db, von: datetime, bis: datetime | None) -> Decimal`.
- `umsatz_im_zeitraum(db, von: date, bis: date | None) -> Decimal`.
- `schuldige_umsatzsteuer(db, von: date, bis: date | None) -> Decimal`.

Die bestehenden Namen `schuldige_umsatzsteuer_ytd`, `nettoumsatz_ytd`, `gmbh_ruecklage_ytd`
und `geschaetzte_steuerabgaben` bleiben erhalten und verhalten sich unveraendert. Die
Erweiterung um eine obere Zeitgrenze geschieht in `_summe_feld` und wird nach oben
durchgereicht; ein fehlendes `bis` heisst weiterhin "ohne obere Grenze".

Die Rueckgabetypen sind unveraenderliche Datensaetze (`@dataclass(frozen=True, slots=True)`),
keine Tupel und keine Dictionaries. Ein Tupel an dieser Stelle waere eine Einladung, die
Reihenfolge im Template zu verwechseln.

## Fachliche Festlegungen

Diese Punkte entscheiden ueber richtig und falsch. Sie sind nicht verhandelbar und je durch
mindestens einen Test zu belegen.

**Was zaehlt als Rechnung.** Ueberall dort, wo von Forderungen die Rede ist, gilt
`Invoice.invoice_type IS NULL`. Eine Gutschrift ist keine offene Forderung und wird nicht
angemahnt. Das entspricht dem heutigen `standard`-Filter in `main.py:280`.

**Offen** heisst `status == "issued"`. `draft` ist noch kein Beleg, `paid` ist erledigt,
`cancelled` und `discarded` sind heraus.

**Ueberfaellig** heisst offen **und** `due_date < heute`. Der Faelligkeitstag selbst ist
nicht ueberfaellig. `aeltester_tage` ist die Differenz in Tagen zwischen heute und dem
kleinsten `due_date` der ueberfaelligen Menge; ohne ueberfaellige Belege ist der Wert `None`
und die Kachel zeigt an dieser Stelle nichts, keine Null.

**Nicht versendet** heisst `status == "issued"` und `datev_sent_at IS NULL`. Das ist genau
die Unterscheidung, die `services/beleg_status.py` bereits trifft; der Hinweisstreifen darf
sie nicht ein zweites Mal selbst formulieren, sondern nutzt dieselbe Bedingung.

**Bezahlt im Monat** bleibt bei `updated_at`, nicht `issue_date`. Das ist eine Naeherung, kein
Zahldatum: `updated_at` bewegt sich bei jeder Aenderung. Die vorhandene Kachel rechnet schon
so, und der Vormonatsvergleich muss dieselbe Naeherung benutzen, sonst vergleicht er zwei
verschiedene Groessen. Der Vormonat ist `updated_at >= vormonat_beginn` und
`updated_at < monat_beginn`; die obere Grenze ist Pflicht, sonst zaehlt der laufende Monat
doppelt.

**Vorjahresvergleich.** Der Vorjahreszeitraum ist der 1. Januar des Vorjahres bis zum selben
Tag und Monat des Vorjahres, jeweils ueber `issue_date`, mit denselben Status- und
Typbedingungen wie `revenue_ytd`. Faellt der heutige Tag auf den 29. Februar, ist die obere
Grenze im Vorjahr der 28. Februar; `date(jahr - 1, 2, 29)` wirft sonst einen `ValueError` und
die Uebersicht bricht an einem Schaltjahr ab. Ist der Vorjahresumsatz null, wird **keine**
Prozentzahl gezeigt, sondern ein Hinweis, dass es keinen Vergleichswert gibt. Eine Division
durch null darf nicht vorkommen, und "plus unendlich Prozent" ist keine Kennzahl.

**Quartals-Umsatzsteuer.** Das laufende Kalenderquartal, also Beginn am 1. Januar, 1. April,
1. Juli oder 1. Oktober, obere Grenze offen. Gerechnet wird mit derselben Funktion wie die
Jahreszahl, nur mit anderem Zeitraum; es entsteht keine zweite Rechenvorschrift fuer
Umsatzsteuer. Die Zeile nennt das Quartal ausdruecklich ("Q3 2026"), weil die Zahl sonst mit
der Jahreszahl darueber verwechselt wird.

**Waehrung.** Alle Betraege werden ohne Ruecksicht auf `invoices.currency` summiert, genau wie
heute. Das ist eine bestehende, bewusst uebernommene Vereinfachung und wird in diesem Auftrag
nicht behoben; sie gehoert aber als Kommentar an die Summenfunktion, damit die naechste
Leserin nicht glaubt, es sei geprueft.

## Verlinkung in die Rechnungsliste

`routers/invoices.list_invoices` kennt heute `status`, `q` und `seite`. Es kommen zwei
optionale Parameter hinzu:

- `art`: `rechnung` filtert auf `invoice_type IS NULL`, `gutschrift` auf
  `invoice_type == "credit_note"`. Leer heisst wie bisher: beides.
- `faellig`: `ueberfaellig` filtert auf `due_date < heute`. Leer heisst: keine Einschraenkung.

Ein unbekannter Wert in `art` oder `faellig` wird als leer behandelt und nicht als Fehler;
die Liste ist keine Schnittstelle, an der ein vertippter Link eine Fehlerseite rechtfertigt.

Diese Parameter sind **notwendig**, nicht schmueckend: die Kachel zaehlt ohne Gutschriften,
`?status=issued` allein zaehlt sie mit. Ohne `art=rechnung` fuehrt ein Klick auf die Zwei zu
drei Zeilen, und die Nutzerin haelt danach die Kachel oder die Liste fuer kaputt.

Die aktive Auswahl muss in der Liste **sichtbar und aufhebbar** sein, in derselben Form, in der
`status_filter` heute schon dargestellt wird. Die Liste reicht `art` und `faellig` wie `status`
und `q` in den Template-Kontext und in die Blaetterlinks; eine Filterung, die beim Umblaettern
verlorengeht, ist schlimmer als keine.

Ziele der Links:

| Element | Ziel |
|---|---|
| Kachel Offene Rechnungen | `/invoices?status=issued&art=rechnung` |
| Kachel Ueberfaellig | `/invoices?status=issued&art=rechnung&faellig=ueberfaellig` |
| Unterzeile Entwuerfe | `/invoices?status=draft` |
| Unterzeile gestellt | `/invoices?status=issued` |
| Unterzeile bezahlt | `/invoices?status=paid` |
| Unterzeile storniert | `/invoices?status=cancelled` |
| Hinweisstreifen | `/invoices?status=issued&art=rechnung` |

Die vier Unterzeilen unter "Rechnungen gesamt" tragen bewusst **kein** `art`, weil sie den
Gesamtbestand aufteilen und ihre Summe der Gesamtzahl entsprechen muss.

## Darstellung

Die Oberflaeche ist ein Terminal-Thema mit Pixelschriften und festen CSS-Variablen. Neue
Elemente uebernehmen die vorhandenen Klassen (`card`, `card-hover`, `kpi__beschriftung`,
`kpi__wert`, `kpi__einheit`, `badge`) und die vorhandenen Farbvariablen. Es werden **keine**
neuen Farben, Schriften oder Abstaende erfunden.

Die Kachel Ueberfaellig nutzt `var(--pink)` in derselben Bauform wie die bestehenden Kacheln,
weil das die einzige Kachel ist, die zum Handeln auffordert. Sind null Belege ueberfaellig,
bleibt die Kachel stehen und zeigt eine ruhige Null in der normalen Textfarbe; sie
verschwindet nicht, denn eine Kachel, die je nach Lage da ist oder nicht, laesst das Raster
springen.

Der Hinweisstreifen dagegen erscheint nur bei Bedarf. Er steht zwischen Kopf und Kachelraster,
nennt die Anzahl und verlinkt in die Liste.

Betraege werden mit den vorhandenen Filtern aus `darstellung.py` formatiert, nicht mit neuen
Formatierungen im Template.

## Tests

Test-first, ohne Ausnahme. Jeder Test mit Datenbankwirkung benutzt die `pg_session`-Fixture;
eine nachgebaute Mock-Datenbank ist hier verboten, weil genau die SQL-Bedingungen der
Gegenstand sind. `backend/tests/test_dashboard.py` enthaelt die Bauhelfer `_inv` und
`_gutschrift` und ist der Ort fuer die Kennzahlen; die Listenfilter gehoeren zu den Tests der
Rechnungsliste.

Mindestens zu belegen:

- Offener Betrag summiert nur `issued`, ohne Entwuerfe, Bezahlte und Stornierte.
- Eine Gutschrift im Status `issued` erhoeht weder Anzahl noch Betrag der offenen Forderungen.
- Faellig heute ist nicht ueberfaellig; faellig gestern ist es.
- `aeltester_tage` ist `None` ohne ueberfaellige Belege und sonst die Differenz zum
  kleinsten `due_date`.
- Der Vormonatsbetrag enthaelt den laufenden Monat nicht.
- Vorjahresvergleich am 29. Februar wirft keinen Fehler.
- Vorjahresumsatz null liefert keine Prozentzahl.
- Quartals-Umsatzsteuer enthaelt eine Rechnung aus dem Vorquartal nicht.
- Nicht versendet zaehlt nur `issued` ohne `datev_sent_at`.
- Der Hinweisstreifen fehlt im HTML, wenn es keinen solchen Beleg gibt.
- `?art=rechnung` blendet Gutschriften aus, `?faellig=ueberfaellig` blendet nicht faellige aus,
  und beide zusammen mit `status` wirken gleichzeitig.
- Die Zahl der Kachel und die Zahl der verlinkten Liste stimmen ueberein. Dieser Test ist der
  wichtigste des Auftrags: er ist der einzige, der die Luecke faengt, wegen der `art`
  ueberhaupt eingefuehrt wird.

Die vorhandenen Tests in `test_dashboard.py` bleiben gruen. Wird `draft_count` im Kontext
umbenannt, werden die dortigen Zusicherungen mitgezogen; ein Umbenennen ohne Not ist aber
unerwuenscht.

**Gruen ist verdaechtig.** Nach dem Umbau der Kennzahlfunktionen einen kleinen Fehler
einbauen, etwa `<` statt `<=` in der Faelligkeitsgrenze, und belegen, dass mindestens ein
Test rot wird; danach zuruecknehmen. Beide Haelften messen, nicht nur die gruene.

## Nicht in diesem Auftrag

Keine Aenderung an Datenbankschema, Migrationen, Modellen, Unveraenderlichkeitswaechtern oder
Triggern. Es entsteht keine neue Spalte. Alle Kennzahlen sind Abfragen auf Bestehendes.
