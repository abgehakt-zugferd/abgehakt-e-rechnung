# Auftrag: Text der Rechnungsmail je Belegsprache konfigurierbar

Stand: 28.09.2026. Spezifikation fuer einen getrennten, test-first auszufuehrenden Auftrag.
Keine Implementierung in dieser Datei. Bestand aus dem Repository wird vorausgesetzt.

## Anlass

Jede Rechnung traegt seit `services/belegsprache.py` eine Belegsprache (`de` oder `en`), die
das PDF vollstaendig steuert: Titel, Feldbeschriftungen, Zahlen- und Datumsformat,
Steuerhinweise. Die Mail, die dieses PDF transportiert, kennt die Sprache nicht.
`build_invoice_body` in `services/datev_email.py:118` hat den deutschen Text fest verdrahtet.

Die Folge ist gemessen und belegt: ein englischer Beleg an einen Kunden im Ausland wird mit
Betreff "Rechnung Z-2026-009" und der Anrede "Sehr geehrte Damen und Herren" verschickt,
waehrend das angehaengte PDF durchgaengig "Invoice number" schreibt. Die Mail verlaesst das
Haus und geht ausserdem als Blindkopie an den Steuerberater; sie ist kein internes Artefakt.

## Ergebnis und fachlicher Umfang

Betreff und Rumpf der Rechnungsmail sind in den Einstellungen hinterlegbar, getrennt je
Sprache. Der Versand waehlt die Schablone **nach `invoices.document_language`**, nicht nach
einer globalen Einstellung und nicht nach dem Land des Kunden. Dieselbe Quelle wie das PDF:
laufen die beiden auseinander, hat man wieder genau das Problem, das dieser Auftrag loest.

Drei Entscheidungen des Auftraggebers, bereits getroffen:

- Aenderbar **nur in den Einstellungen**. Der Sendedialog bekommt kein Textfeld. Ein je
  Versand ueberschriebener Text muesste im `InvoiceSendLog` mitprotokolliert werden, sonst
  weiss hinterher niemand, was rausging; das ist ein eigener Auftrag.
- Der **Betreff ist mitkonfigurierbar**, je Sprache. Ohne ihn bliebe der englische Kunde bei
  einem deutschen Betreff, und das ist der sichtbarste Teil des Problems.
- Nur die **Rechnungsmail**. Die SMTP-Testmail (`build_test_mail`) bleibt unveraendert
  deutsch; sie geht an die Betreiberin und nie an einen Kunden. Die Storno- und
  Gutschriftmail laeuft ueber denselben Versandweg und erbt die Sprache dadurch von selbst.

## Naht und Vertrag

Es entsteht `backend/app/services/mailtext.py`. `datev_email.py` sendet danach nur noch und
verfasst nichts mehr; `build_invoice_body` zieht mitsamt Verhalten in das neue Modul um.

Das neue Modul haengt an `belegsprache` und am `Company`-Datensatz, aber nicht an SMTP, HTTP
oder Jinja. Ein Text laesst sich damit erzeugen und pruefen, ohne dass ein Mailserver
existiert. Das ist der Grund fuer die Trennung: heute ist der einzige Weg zum Mailtext ein
`send_invoice`, das gleichzeitig eine Verbindung aufbaut.

Schnittstelle als Spezifikation, nicht als auszufuehrender Code:

- `Mailinhalt`: unveraenderlicher Datensatz mit `betreff` und `rumpf`.
- `rechnungsmail(invoice, company, config) -> Mailinhalt`
- `standardschablone(sprache) -> Schablone` liefert den eingebauten Text der Sprache.
- `pruefe_schablone(text: str) -> None`, wirft `UnbekannterPlatzhalterError(name)`.
- `PLATZHALTER: tuple[str, ...]` ist die einzige Liste der erlaubten Namen. Weder Template
  noch Einstellungsseite fuehren eine zweite.

`send_invoice` bekommt den fertigen `Mailinhalt` uebergeben und baut keinen Text mehr selbst.

## Speicherung

Vier neue, `nullable` Spalten an `AppConfig` samt Alembic-Migration, in der Reihenfolge der
bestehenden Konfigurationsfelder:

| Spalte | Typ |
|---|---|
| `mail_betreff_de` | `String(200)` |
| `mail_text_de` | `Text` |
| `mail_betreff_en` | `String(200)` |
| `mail_text_en` | `Text` |

`NULL` oder leer heisst: der eingebaute Text der Sprache gilt. Damit braucht die Migration
keine Daten zu schreiben, und eine bestehende Installation verschickt nach dem Update
buchstabengleich dieselbe deutsche Mail wie vorher. Das ist eine Zusicherung und wird
getestet.

Ein Feld leeren stellt den eingebauten Text wieder her. Es gibt keinen dritten Zustand und
keinen gesonderten Zuruecksetzen-Knopf.

Die Migration muss zu `alembic check` gegen die Modelle passen, wie jede andere in der Kette.

## Platzhalter

Erlaubt sind genau fuenf Namen, in geschweiften Klammern, kleingeschrieben:

| Platzhalter | Inhalt |
|---|---|
| `{rechnungsnummer}` | `invoice.invoice_number` |
| `{kunde}` | Name des Kunden, leer wenn keiner hinterlegt ist |
| `{betrag}` | `gross_total`, formatiert ueber `belegsprache.darstellung(sprache).format_betrag` mit `invoice.currency` |
| `{faellig_am}` | `due_date` ueber `format_datum` derselben Darstellung |
| `{firma}` | `company.name`, sonst leer |

Betrag und Datum kommen damit in der Schreibweise des Belegs: `1.234,56 €` und `28.09.2026`
im deutschen, `EUR 1,234.56` und `2026-09-28` im englischen Beleg. Eine zweite
Formatierungsvorschrift fuer Mails entsteht nicht.

Massgeblich ist `format_betrag`, nicht dieses Beispiel: die Funktion setzt bei `currency == "EUR"`
im deutschen Beleg das Eurozeichen und schreibt den Code nur bei einer anderen Waehrung aus.

**Ersetzt wird ueber einen eigenen, engen Ausdruck**, nicht ueber `str.format` und
ausdruecklich nicht ueber Jinja. `str.format` gibt einem hinterlegten Text Zugriff auf
Attribute und Indizes der uebergebenen Werte; Jinja gaebe ihm eine Programmiersprache. Der
Text ist von aussen gepflegter Inhalt, und die erzeugte Mail geht an Dritte. Vorgesehen ist
ein Ersetzen aller Vorkommen von `\{([a-z_]+)\}` gegen die bekannten Werte.

Ein unbekannter Platzhalter ist ein **Fehler beim Speichern** in den Einstellungen, mit
Nennung des Namens, und nicht beim Senden. Eine Mail, die im Moment des Versands an einem
Tippfehler zerbricht, scheitert an der teuersten Stelle: der Beleg ist dann schon finalisiert.

Geschweifte Klammern ohne bekannten Namen darin bleiben unveraendert stehen, statt eine
Ausnahme zu werfen. Ein Text mit `{` in einer Produktbezeichnung darf nicht unversendbar sein.

Nach dem Ersetzen werden Leerzeilen am Ende entfernt, damit ein leeres `{firma}` keine
baumelnde Leerzeile hinterlaesst.

## Was nicht konfigurierbar ist

**Der Verantwortlichen-Fuss bleibt ausserhalb der Schablone** und wird wie heute in
`_anschrift(company)` gebildet und angehaengt. Der Docstring von `build_invoice_body` nennt
den Grund, und er gilt unveraendert: die Zeile benennt gegenueber Kunde und Steuerberater die
datenschutzrechtlich verantwortliche Stelle. Eine frei editierbare Angabe dort koennte einen
fremden Dritten zum Verantwortlichen fuer fremde Daten erklaeren. Keine Angabe ist besser als
eine falsche. Das Label folgt der Belegsprache: `Verantwortlich:` beziehungsweise
`Responsible:`.

**Der `[TESTINSTANZ]`-Vorsatz** in Betreff und Rumpf bleibt, wo er ist, und laesst sich nicht
wegkonfigurieren. Er ist die einzige Sicherung dagegen, dass eine Testpost fuer eine echte
Rechnung gehalten wird.

## Eingebaute Texte

Deutsch ist Wort fuer Wort der heutige Text aus `build_invoice_body`, damit ein Update nichts
aendert. Englisch ist dessen Uebersetzung. Beide gehoeren in `mailtext.py` und werden nicht
vom Auftragnehmer neu erfunden.

Betreff `de`: `Rechnung {rechnungsnummer}`
Betreff `en`: `Invoice {rechnungsnummer}`

Rumpf `en`:

```
Dear Sir or Madam,

please find attached your invoice {rechnungsnummer}.

The document contains the structured ZUGFeRD invoice data (Factur-X EN16931)
pursuant to section 14 of the German VAT Act (UStG).

Please do not hesitate to contact us if you have any questions.

Kind regards
{firma}
```

Der deutsche eingebaute Rumpf nennt die Firma heute nur, wenn sie gesetzt ist. Mit `{firma}`
als Platzhalter und der Leerzeilenregel oben bleibt dieses Verhalten erhalten.

## Sprachwahl beim Versand

Die Sprache kommt ueber `belegsprache.resolve_belegsprache(invoice.document_language)`. Ein
gespeicherter Wert, der weder `de` noch `en` ist, faellt **nicht** still auf Deutsch zurueck,
sondern laesst den Versand mit einer verstaendlichen Meldung scheitern. Das ist die
ausdrueckliche Doktrin des Moduls: ein fremdsprachiger Beleg darf nicht unbemerkt falsch
beschriftet werden. Die Spalte hat `server_default="de"` und ist `not null`; der Fall ist
damit praktisch ausgeschlossen und die Pruefung trotzdem am Platz.

## Oberflaeche

`templates/settings/index.html` bekommt einen Abschnitt "Text der Rechnungsmail", eingeordnet
neben den SMTP-Feldern, mit vier Eingaben: Betreff und Rumpf je Sprache. Der Rumpf ist ein
`textarea`, ausreichend hoch fuer den eingebauten Text ohne Scrollen.

Der Abschnitt nennt die erlaubten Platzhalter sichtbar, erzeugt aus `mailtext.PLATZHALTER`,
und sagt in einem Satz, dass ein leeres Feld den eingebauten Text bedeutet und dass sich die
Sprache aus der jeweiligen Rechnung ergibt, nicht aus dieser Seite.

Ein Speicherfehler wegen eines unbekannten Platzhalters wird am Feld angezeigt, und die
Eingaben bleiben stehen. Ein verworfener Text waere hier besonders aergerlich: es ist ein
Fliesstext, kein Kontrollkaestchen.

Bestehende Klassen, Farben und Schriften der Einstellungsseite werden uebernommen. Keine neuen
Gestaltungselemente.

## Tests

Test-first, ohne Ausnahme.

Rein und ohne Datenbank in `mailtext.py` pruefbar:

- Jeder der fuenf Platzhalter wird ersetzt.
- Ein unbekannter Name wirft beim Pruefen und nennt ihn.
- Geschweifte Klammern ohne bekannten Namen bleiben stehen.
- Betrag und Datum folgen der Sprache: deutsches und englisches Ergebnis unterscheiden sich
  nachweislich in Trennzeichen und Datumsform.
- Leeres `{firma}` hinterlaesst keine Leerzeile am Ende.
- Der Verantwortlichen-Fuss steht unabhaengig von der Schablone am Ende, auch bei einer
  Schablone, die ihn zu setzen versucht.

Mit `pg_session`, weil `AppConfig` beteiligt ist:

- Ohne hinterlegten Text ist der deutsche Rumpf **zeichengleich** mit dem heutigen. Der
  Vergleichstext steht im Test ausgeschrieben, nicht als Aufruf derselben Funktion, die
  geprueft wird.
- Ein hinterlegter deutscher Text wirkt auf eine Rechnung mit `document_language == "de"` und
  nicht auf eine mit `en`, und umgekehrt.
- Ein Feld leeren stellt den eingebauten Text wieder her.
- Speichern mit unbekanntem Platzhalter wird abgelehnt und veraendert die Zeile nicht.
- Der Betreff folgt der Belegsprache.
- In der Testinstanz traegt der Betreff weiterhin den Vorsatz, auch bei hinterlegtem Text.
- `alembic check` bleibt sauber.

Uebersprungene Tests gelten als Fehlschlag. Der Versandweg wird mit einem Doppel fuer SMTP
geprueft, nicht durch Auslassen.

**Gruen ist verdaechtig.** Nach dem Umzug von `build_invoice_body` einen kleinen Fehler
einbauen, etwa die Sprachwahl fest auf `de` verdrahten, und belegen, dass mindestens ein Test
rot wird; danach zuruecknehmen. Der Sprachzweig ist eine Fallunterscheidung mit zwei Wegen zum
selben Modul, deshalb den gesamten Entscheidungsweg brechen und nicht nur einen Zweig.

## Nicht in diesem Auftrag

Kein Textfeld im Sendedialog. Keine dritte Sprache. Keine HTML-Mail; der Versand bleibt reiner
Text. Keine Aenderung an Anhang, Empfaengerlogik, `InvoiceSendLog` oder an der Testmail.
