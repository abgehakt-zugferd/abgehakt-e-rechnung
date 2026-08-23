# Anwendung

Dieses Dokument beschreibt, wie mit Abgehakt gearbeitet wird. Es beantwortet keine
steuerlichen Fragen und ersetzt keine Beratung; es beschreibt nur, was das Programm tut und
warum es sich an manchen Stellen weigert.

Die Installation und die Ersteinrichtung stehen in [README.md](../README.md). Der innere
Aufbau steht in [ARCHITEKTUR.md](ARCHITEKTUR.md).

## Der Lebenslauf eines Belegs

| Zustand | Bedeutung |
|---|---|
| **Entwurf** | Frei änderbar. Die Rechnungsnummer ist bereits vergeben, der Beleg selbst existiert noch nicht. |
| **Verworfen** | Ein Entwurf, den Sie nicht mehr wollten. Er bleibt als Datensatz erhalten und erklärt später die Lücke im Nummernkreis. Zurückholen ist möglich. |
| **Gestellt** | Das ZUGFeRD-PDF ist erzeugt und liegt im Archiv. Ab hier ist nichts mehr änderbar. |
| **Bezahlt** | Das Geld ist eingegangen. Endzustand. |
| **Storniert** | Der Beleg wurde durch eine Gutschrift aufgehoben. Endzustand. |

Der Übergang vom Entwurf zum gestellten Beleg heißt **Finalisieren** und ist der einzige
Schritt, der sich nicht zurücknehmen lässt. Alles davor ist Arbeitsstand, alles danach ist
aufbewahrungspflichtig.

Finalisieren gelingt entweder ganz oder gar nicht. Lässt sich die E-Rechnungs-XML nicht
prüffähig ins PDF einbetten, bleibt die Rechnung Entwurf, und es entsteht keine Datei. Ein
PDF ohne eingebettete XML ist seit 2025 keine gültige Rechnung, und das Programm legt
lieber nichts ab als etwas Unbrauchbares.

---

## Anwendungsfall: eine gestellte Rechnung korrigieren

### Warum es keinen Knopf zum Ändern gibt

Ein gestellter Beleg ist unveränderlich. Das ist keine Bequemlichkeitsentscheidung des
Programms, sondern die Grundlage dafür, dass die Buchführung nachvollziehbar bleibt: eine
Rechnung, die sich nachträglich ändern lässt, beweist nichts. Wer den Empfänger, den Betrag
oder die Leistung korrigieren muss, hebt den alten Beleg auf und schreibt einen neuen.

Das Aufheben heißt hier **Stornierung** und erzeugt eine **Gutschrift**: einen eigenen
Beleg mit eigener Rechnungsnummer, der auf das Original verweist und es betragsgleich
neutralisiert. Beide Belege bleiben erhalten, und beide gehen an die Buchhaltung.

### Schritt für Schritt

1. Öffnen Sie die gestellte Rechnung.
2. **Stornorechnung erzeugen.** Es entsteht ein Entwurf einer Gutschrift, der die Beträge
   und Positionen des Originals unverändert übernimmt.
3. Prüfen Sie den Entwurf und **finalisieren** Sie ihn. Jetzt entsteht das ZUGFeRD-PDF der
   Gutschrift.
4. Senden Sie die Gutschrift an Ihre Kundin oder Ihren Kunden und an die Buchhaltung, so wie
   Sie es mit der Originalrechnung getan haben.
5. Setzen Sie das **Original** auf **storniert**. Dieser Schritt bleibt Ihnen überlassen,
   siehe unten.
6. Schreiben Sie, falls nötig, eine neue, korrekte Rechnung. Sie ist ein eigenständiger
   Beleg und bezieht sich nicht auf die Gutschrift.

### Was das Programm dabei verweigert, und warum

**Sie können eine Gutschrift nicht bearbeiten.**
Eine Gutschrift spiegelt ihr Original. Ließe sie sich ändern, entstünde eine „Gutschrift zu
RE-001" mit anderen Zahlen, und das ist keine Stornierung mehr, sondern eine Teilkorrektur.
Stimmt am Entwurf etwas nicht, verwerfen Sie ihn und beginnen neu.

**Sie können denselben Beleg nicht zweimal stornieren.**
Zwei Gutschriften zum selben Beleg würden die Forderung doppelt mindern, in der Offene-Posten-Liste
wie in der Buchhaltung. Auch ein noch offener Gutschrifts-Entwurf sperrt den zweiten
Versuch: sonst gäbe es zwei Entwürfe, die beide finalisierbar wären, und der Fehler fiele
erst auf, wenn schon ein Beleg im Archiv liegt.

Ein **verworfener** Gutschrifts-Entwurf sperrt dagegen nicht. Wer versehentlich storniert
und den Entwurf verwirft, kann den Beleg erneut stornieren; ein Fehlgriff ist nicht
endgültig.

**Sie können ein storniertes Original nicht als bezahlt markieren.**
Ein Beleg, der aufgehoben wurde, kann nicht gleichzeitig beglichen sein. Ist das Geld
tatsächlich geflossen und Sie erstatten es, gehört das an die Gutschrift: die dürfen Sie als
bezahlt markieren, und dort heißt bezahlt schlicht erstattet.

### Warum das Original nicht von selbst auf „storniert" springt

Das Programm setzt den Status des Originals nicht automatisch. Der Grund ist unangenehm
konkret: **bezahlt** ist ein Endzustand, aus dem kein Weg mehr herausführt, und eine bereits
bezahlte Rechnung darf storniert werden. Eine Automatik würde also für gestellte Rechnungen
greifen und für bezahlte stillschweigend nicht, also in genau der Hälfte der Fälle. Eine
Regel, die manchmal wirkt, ist schlimmer als keine, weil niemand ihr ansieht, wann sie
gewirkt hat.

Statt die Zustandsregeln aufzuweichen, bleibt der Schritt bei Ihnen. Solange Sie ihn nicht
tun, steht die stornierte Rechnung weiterhin als **gestellt** in der Liste und zählt auf dem
Dashboard mit.

### Der Sonderfall: die Rechnung war schon bezahlt

Eine bezahlte Rechnung lässt sich stornieren, ihr Status bleibt danach aber auf **bezahlt**
stehen. Aus dem Endzustand bezahlt führt kein Übergang mehr heraus. Die Gutschrift ist der
Beleg für die Aufhebung, und die Buchhaltung liest die Kombination aus beiden Belegen
richtig. Wenn Sie in der Liste dennoch sehen wollen, dass hier etwas rückgängig gemacht
wurde: die Gutschrift steht direkt darunter und verweist auf die Nummer des Originals.

### Was das Programm nicht kann

**Teilkorrekturen.** Eine Rechnung, von der nur eine Position falsch ist, wird hier
vollständig storniert und neu geschrieben. Der Belegtyp für eine echte Teilkorrektur
(Rechnungskorrektur, TypeCode 384) ist im Format vorgesehen, hat aber keinen Weg über die
Oberfläche. Eine Gutschrift mit abweichenden Beträgen wäre eine Teilkorrektur durch die
Hintertür, und genau deshalb wird sie abgewiesen.

**Löschen.** Weder Rechnungen noch Kunden werden je gelöscht. Ein Entwurf lässt sich
verwerfen, ein Kunde inaktiv setzen; die Datensätze bleiben, weil sonst Nummern fehlen
würden, die niemand mehr erklären kann.
