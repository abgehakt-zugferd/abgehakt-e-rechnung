# GoBD-Wissensdatenbank

Stand: 2026-06-11 | Quelle: AWV GoBD-Praxisleitfaden v2.2 (auf GoBD 2019 basierend) + BEG IV (2024)

---

## 1. Rechtsgrundlagen

| Norm | Inhalt |
|------|--------|
| **§§ 238 ff. HGB** | Handelsrechtliche Buchführungspflicht, Grundsätze ordnungsmäßiger Buchführung (GoB) |
| **§§ 140–148 AO** | Steuerrechtliche Aufzeichnungs- und Aufbewahrungspflichten |
| **§ 146 AO** | Zeitgerechte, vollständige, richtige, geordnete Buchführung; Unveränderbarkeit |
| **§ 147 AO** | Aufbewahrungspflichten und -fristen (seit BEG IV: 8 Jahre für Buchungsbelege) |
| **§ 14b UStG** | Aufbewahrungspflicht für Rechnungen (**8 Jahre** seit 1.1.2025, vorher 10 Jahre) |
| **GoBD** | BMF-Schreiben v. 28.11.2019, Grundsätze zur ordnungsmäßigen Führung und Aufbewahrung von Büchern, Aufzeichnungen und Unterlagen in elektronischer Form |

---

## 2. Aufbewahrungsfristen (Stand 2025)

### ⚠️ Wichtig: BEG IV (Bürokratieentlastungsgesetz IV, in Kraft ab 1.1.2025)

Das BEG IV hat §14b Abs. 1 UStG **und** §147 Abs. 3 AO geändert: Die Aufbewahrungsfrist für Buchungsbelege (inkl. Rechnungen) wurde von **10 auf 8 Jahre** verkürzt. Gilt auch rückwirkend für Belege, deren 10-Jahres-Frist am 31.12.2024 noch nicht abgelaufen war.

| Unterlage | Frist | Norm |
|-----------|-------|------|
| Rechnungen (Ein- und Ausgang) | **8 Jahre** | §14b UStG (ab 1.1.2025) |
| Buchungsbelege | **8 Jahre** | §147 Abs. 3 AO (ab 1.1.2025) |
| Bücher, Inventare, Jahresabschlüsse, Lageberichte, Eröffnungsbilanzen, Organisations­unterlagen | **8 Jahre** | §147 Abs. 3 AO (ab 1.1.2025) |
| Empfangene/gesandte Handelsbriefe | **6 Jahre** | §147 Abs. 3 AO |
| Sonstige steuerrelevante Unterlagen | **6 Jahre** | §147 Abs. 3 AO |
| Aufzeichnungen nach §22 UStG | **10 Jahre** | §22 UStG (NICHT durch BEG IV geändert) |
| Jahresabschlüsse nach HGB | **10 Jahre** | §257 HGB (NICHT durch BEG IV geändert) |

**Gilt immer die längere Frist**: Wenn ein Dokument in mehrere Kategorien fällt, gilt die längste zutreffende Frist.

**Ablaufhemmung** (§171 AO): Die Aufbewahrungsfrist läuft nicht ab, solange die Unterlagen für noch laufende Steuerfestsetzungen relevant sind.

### Für dieses System

- `invoice.archive_until = berechne_archive_until(issue_date)` mit Fristende am **31.12. des (Ausstellungsjahr + 8)**
- Fristbeginn: Ende des Kalenderjahres, in dem die Rechnung ausgestellt wurde (§147 Abs. 4 AO)
- Effektive Mindestaufbewahrung: meist **9 Jahre** ab Ausstellungsdatum (wegen Jahresendprinzip)

---

## 3. GoBD-Grundsätze

### 3.1 Grundsatz der Nachvollziehbarkeit und Nachprüfbarkeit
- Jeder Geschäftsvorfall muss vom Beleg bis zum Jahresabschluss **progressiv** und **retrograd** nachvollziehbar sein
- Alle Verarbeitungsschritte müssen dokumentiert und prüfbar bleiben

### 3.2 Grundsatz der Vollständigkeit
- Alle Geschäftsvorfälle müssen erfasst werden, keine Auslassung
- Vollständige Erfassung aller steuerrelevanten Daten

### 3.3 Grundsatz der Richtigkeit
- Sachliche und rechnerische Richtigkeit aller Buchungen
- Verstöße müssen als Storno kenntlich gemacht werden, nicht überschrieben

### 3.4 Grundsatz der zeitgerechten Buchungen (§146 Abs. 1 AO)
- **Bareinnahmen/-ausgaben:** täglich festzuhalten (§146 Abs. 1 S. 2 AO)
- **Unbare Geschäftsvorfälle:** innerhalb von **10 Tagen** unbedenklich
- Ziel: Verhindern, dass Vorfälle buchungsmäßig in der Schwebe gehalten werden

### 3.5 Grundsatz der Unveränderbarkeit (§239 Abs. 3 HGB, §146 Abs. 4 AO)

**Kritisch für Softwaresysteme:**
- Keine stille Überschreibung oder Löschung gebuchter Daten
- Korrekturen nur als **Stornobuchungen** mit Verweis auf den Originalbeleg
- Änderungen müssen jederzeit erkennbar sein (Zeitpunkt, Art der Änderung)
- Buchführungssoftware muss Änderungen **automatisch aufzeichnen** (Audit Trail)

**Implementierung hier:**
- Finalisierte Rechnungen (`status = issued/paid/cancelled`) sind unveränderlich ✓
- Kein Hard-Delete, nur Soft-Delete über Status/`deleted_at` ✓
- `audit_log`-Tabelle protokolliert Änderungen mit `old_values`/`new_values` ✓

### 3.6 Grundsatz der Ordnung
- Geordnete, systematische Ablage aller Unterlagen
- Jederzeit abrufbar und ohne unangemessene Verzögerung lesbar

---

## 4. Maschinelle Auswertbarkeit und Datenzugriff

Die Finanzbehörde hat bei einer Außenprüfung drei Arten des Datenzugriffs (§147 Abs. 6 AO):

| Zugriff | Beschreibung |
|---------|--------------|
| **Z1** | Unmittelbarer Datenzugriff auf das Produktivsystem |
| **Z2** | Mittelbarer Datenzugriff durch sachverständigen Mitarbeiter des Steuerpflichtigen unter Prüfervorgaben |
| **Z3** | Datenübertragung in maschinell auswertbarem Format (früher: „Datenträgerüberlassung") |

**Anforderungen:**
- Alle aufbewahrungspflichtigen Daten müssen **während der gesamten Aufbewahrungsfrist** maschinell auswertbar bleiben
- Das gilt auch für Daten aus abgelösten Altsystemen (Systemwechsel)
- Erleichterung (GoBD Rz. 164): Ab dem **6. Jahr nach Systemwechsel** kann auf Z1/Z2-Zugriff verzichtet werden (sofern keine Außenprüfung begonnen hat)

**ZUGFeRD-Vorteil:**
- ZUGFeRD-Rechnungen als strukturiertes XML erfüllen automatisch die Anforderung an maschinelle Auswertbarkeit
- Bei gleichem Inhalt hat das Format mit **höchster maschineller Auswertbarkeit** Vorrang (GoBD Rz. 76): XML > PDF > Papier
- Seit 1.1.2025 hat der XML-Teil der ZUGFeRD-Rechnung **rechtlichen Vorrang** vor dem PDF

---

## 5. Aufbewahrung digitaler Unterlagen

### Originär digitale Dokumente
- Müssen **im Originalformat** aufbewahrt werden (nicht nur als Ausdruck)
- Elektronisch empfangene Rechnungen (E-Mails, PDF, ZUGFeRD) müssen elektronisch archiviert werden; ein Papierausdruck genügt **nicht**

### Konvertierung (GoBD Rz. 135)
- Bei verlustfreier Konvertierung (kein Inhaltsverlust, keine Einschränkung der Auswertbarkeit) reicht die **konvertierte Version** alleine
- Konvertierungsprozess muss in der **Verfahrensdokumentation** beschrieben werden

### Identische Mehrstücke (GoBD Rz. 76)
- Liegt ein Beleg sowohl als CSV/XML als auch als PDF vor, genügt das Format mit höchster maschineller Auswertbarkeit
- Papierausdrucke zusätzlich zu elektronischen Originalen sind **nicht erforderlich**

### Ausgangsrechnungen aus Fakturierungssystem (GoBD Rz. 76)
- Kein bildliches Archiv des PDFs nötig, wenn jederzeit ein inhaltsgleiches Duplikat erzeugt werden kann UND:
  - Unveränderbarkeit der Daten sichergestellt
  - Maschinelle Auswertbarkeit gegeben
  - Stammdaten, AGB und Originallayouts historisiert

---

## 6. Verfahrensdokumentation

**Pflicht für alle Unternehmen**, unabhängig von Größe oder Komplexität.

Vier Bestandteile (GoBD Rz. 153):

| Bestandteil | Inhalt |
|-------------|--------|
| **Allgemeine Beschreibung** | Rahmenbedingungen, Aufgabenstellung, Einsatzgebiet, Freigabedokumentation, Gültigkeit |
| **Anwenderdokumentation** | Fachliche Prozesse, Datenerfassung, Prüfung, Abstimmung, Ausgabe, Liste der Daten-/Dokumentenbestände |
| **Betriebsdokumentation** | Technischer Betrieb, Datensicherung, Zugriffsberechtigungen, Systemumgebung |
| **Technische Systemdokumentation** | Systemarchitektur, Schnittstellen, Datenmodell, Verarbeitungsregeln |

**Aufbewahrung:** Für die Dauer der Aufbewahrungspflicht des Systems + Folgejahre.

**Fehlende Verfahrensdokumentation** ist ein formeller Mangel → kann zu Schätzung der Besteuerungsgrundlagen führen.

---

## 7. GoBD-Anforderungen an dieses System (Checkliste)

| Anforderung | Implementierung | Status |
|-------------|-----------------|--------|
| Kein Hard-Delete Rechnungen | `status = cancelled` statt DELETE | ✅ |
| Kein Hard-Delete Kunden | `deleted_at` Soft-Delete | ✅ |
| Unveränderbarkeit finalisierter Rechnungen | `status = issued/paid/cancelled` → read-only | ✅ |
| Audit Trail | `audit_log`-Tabelle mit `old_values`/`new_values` | ✅ |
| `archive_until` = 8 Jahre (ab 2025) | 31.12. des (Ausstellungsjahr + 8) | ✅ |
| ZUGFeRD XML in DB gespeichert | `invoices.zugferd_xml` | ✅ |
| Maschinelle Auswertbarkeit | ZUGFeRD EN16931 (kein MINIMUM/BASIC-WL) | ✅ |
| Stornierung mit Verweis auf Original | TODO: Stornorechnung referenziert Originalrechnung | ⚠️ |
| Verfahrensdokumentation | Noch nicht erstellt | ⬜ |
| Datenzugriff Z3 (Export) | Noch nicht implementiert (DATEV-Export reicht nicht) | ⬜ |

---

## 8. Wichtige Abgrenzungen

### Was ist KEIN GoBD-Verstoß
- E-Mails ohne steuerlichen Inhalt (analog Briefumschlag) → nicht aufbewahrungspflichtig
- Strategieunterlagen, interne Präsentationen (ohne Buchführungsbezug)
- Private Unterlagen

### Was ist definitiv aufbewahrungspflichtig
- **Rechnungen** (Ein- und Ausgang, §14b UStG) → 8 Jahre
- **Buchungsbelege** (Kontoauszüge, Auftragsscheine, Lieferscheine)
- **Handels-/Geschäftsbriefe** (inkl. E-Mails mit Vertragsinhalt) → 6 Jahre
- **Verfahrensdokumentation**
- **Systemdokumentation** der eingesetzten EDV-Programme

---

## 9. Quellen und Weiterführendes

- AWV GoBD-Praxisleitfaden v2.2: `knowledge/GoBD/34231-w_GoBD-Praxisleitfaden_2.2.pdf`
- BMF-Schreiben GoBD v. 28.11.2019 (offiziell maßgeblich)
- BEG IV: BGBl. I 2024 Nr. 278 (in Kraft ab 1.1.2025)
- BMF-Schreiben zu §14b UStG-Änderungen v. 8.7.2025
- §14b UStG aktuell: https://www.gesetze-im-internet.de/ustg_1980/__14b.html
