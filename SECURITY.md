# Sicherheitslücken melden

## Meldeweg

Bitte **nicht** als öffentliches Issue, sondern per E-Mail an **patrick@saleshero.training**,
Betreff `Sicherheit: Abgehakt`.

Hilfreich sind: eine Beschreibung des Fehlers, die Schritte zum Nachstellen, die betroffene
Version (im Seitenfuß der Anwendung) und, falls vorhanden, ein Nachweis. Bitte keine echten
Rechnungs- oder Kundendaten mitschicken.

## Was zugesagt wird

Dieses Projekt wird von einer einzelnen Person betreut. Deshalb steht hier nur, was auch
gehalten werden kann:

- **Eingangsbestätigung innerhalb von 7 Tagen.** Kommt keine, ist die Mail vermutlich nicht
  angekommen; dann bitte nachfassen.
- **Eine Einschätzung, ob und wie die Lücke behoben wird**, sobald sie vorliegt. Ein festes
  Zeitfenster für den Fix wird bewusst nicht versprochen.
- **Nennung in den Anmerkungen zur Veröffentlichung**, wenn das gewünscht ist.

Ein Bug-Bounty-Programm gibt es nicht.

## Unterstützte Version

Nur der aktuelle Stand des `main`-Zweigs. Ältere Stände erhalten keine Sicherheitsupdates.

## Was in den Zuständigkeitsbereich fällt

Das Programm ist dafür gebaut, **lokal** zu laufen, auf dem eigenen Rechner oder in einem
eigenen Netz. Es bringt **keine Benutzerverwaltung und keine Anmeldung** mit: wer die
Oberfläche erreicht, darf alles. Das ist eine bewusste Entscheidung, kein übersehener Fehler.

Daraus folgt für Meldungen:

- **Relevant** sind unter anderem: Umgehung der Aufbewahrungsregeln (Löschen oder
  nachträgliches Ändern eines finalisierten Belegs), SQL-Injection, Ausführen fremden Codes,
  XXE beim Verarbeiten fremder XML, Preisgabe von Zugangsdaten oder des Schlüssels aus
  `storage/secret.key`, Wege aus dem Container heraus.
- **Nicht relevant** ist die fehlende Anmeldung als solche. Wer die Anwendung ins offene
  Internet stellt, hat sie außerhalb ihres vorgesehenen Betriebs eingesetzt. Das ist in der
  Doku so gesagt und keine Lücke im Programm.
