# E-Rechnungspflicht: Wissensdatenbank

Stand: 2026-06-11 | Quelle: Steuerberater-Newsletter + §14 UStG (Wachstumschancengesetz 2024)

---

## Rechtliche Grundlage

**§ 14 UStG in der Fassung des Wachstumschancengesetzes (2024)**

Betrifft: alle inländischen **B2B**-Umsätze (Unternehmer → Unternehmer mit Sitz in Deutschland).
Nicht betroffen: B2C (Endverbraucher), grenzüberschreitende Leistungen.

---

## Stufenplan E-Rechnungspflicht

### ✅ Ab 01.01.2025: Empfangspflicht (bereits in Kraft)

- Alle inländischen B2B-Unternehmen **müssen E-Rechnungen empfangen und verarbeiten** können
- Zulässige Formate: **XRechnung** und **ZUGFeRD** (strukturiertes XML, EN16931)
- Papierrechnungen nur noch mit **ausdrücklicher Zustimmung des Empfängers** zulässig
- Normale PDF-Rechnungen im B2B-Verkehr sind **nicht mehr statthaft**
- **Ausnahme:** Rechnungen unter 250 EUR (Kleinbetragsregelung §33 UStDV)

### ⏳ Ab 01.01.2027: Sendepflicht (Stufe 1)

- Alle Unternehmen **müssen E-Rechnungen versenden**
- **Übergangsfrist bis 31.12.2027:** Unternehmen mit Vorjahresumsatz **unter 800.000 EUR** dürfen noch sonstige Rechnungen (Papier, PDF) senden, müssen aber E-Rechnungen empfangen können
- Wer sendepflichtig ist, hängt am Vorjahresumsatz: unter/über 800.000 EUR entscheidet zwischen 2027 und 2028

### ⏳ Ab 01.01.2028: Sendepflicht für alle

- **Alle Unternehmen** müssen E-Rechnungen senden und empfangen, unabhängig vom Umsatz
- Dauerhafte Ausnahmen bleiben (BMF-FAQ, geprüft 2026-07-11): Kleinbeträge ≤ 250 € brutto
  (§ 33 UStDV), Fahrausweise (§ 34 UStDV), **Kleinunternehmer-Ausgangsrechnungen
  (§ 34a UStDV)**, B2C, steuerfreie Umsätze § 4 Nr. 8–29 UStG, Leistungen an
  juristische Personen ohne Unternehmereigenschaft (z. B. Vereine)

---

## Konsequenz: Vorsteuerabzug wird zum Risiko

BMF-FAQ: „Solange eine sonstige Rechnung ausgestellt werden darf, gilt eine solche
Rechnung für den Vorsteuerabzug weiterhin als ordnungsmäßige Rechnung." Das heißt:

- **2025–2026:** Papier-/PDF-Eingangsrechnungen bleiben für den Vorsteuerabzug in Ordnung.
- **2027:** Eine Papier-/PDF-Rechnung ist nur noch ordnungsgemäß, wenn der **Aussteller**
  sie noch stellen durfte (Vorjahresumsatz ≤ 800.000 €); was der Empfänger nicht
  prüfen kann. Rechnungen großer Lieferanten in Papier/PDF gefährden den Vorsteuerabzug.
- **Ab 2028:** Pflicht-E-Rechnung im B2B (außer dauerhafte Ausnahmen oben); falsche
  Verbuchung → Steuernachzahlungen bei der nächsten Betriebsprüfung.

---

## GoBD-Anforderungen für E-Rechnungen

Die GoBD gelten unverändert auch für E-Rechnungen:

1. **Unmittelbare Sicherung**: E-Rechnungen müssen „unmittelbar nach Eingang oder Entstehung gegen Verlust gesichert werden" (Archivierungspflicht)
2. **Revisionssichere Archivierung**: Ein revisionssicheres E-Rechnungs-Archivierungssystem ist Pflicht
3. **Progressive und retrograde Prüfung**: Muss für die gesamte Dauer der Aufbewahrungsfrist und in jedem Verfahrensschritt möglich sein
4. **Unveränderbarkeit**: Einmal archivierte E-Rechnungen dürfen nicht verändert werden
5. **Maschinelle Auswertbarkeit**: Das XML muss lesbar und auswertbar bleiben (kein Scan eines Ausdrucks)

---

## Zulässige E-Rechnungsformate

| Format | Standard | Verwendung |
|--------|----------|------------|
| **ZUGFeRD** (Factur-X) | EN16931, mind. Profil EN16931 | PDF mit eingebettetem XML, für Empfänger lesbar und maschinell auswertbar |
| **XRechnung** | EN16931 | Reines XML, primär für Behörden/öffentliche Auftraggeber |

**Nicht zulässig** ab 2027 im B2B (Aussteller > 800.000 € Vorjahresumsatz), ab 2028 für alle: reine PDF-Rechnungen, Word-Dokumente, Papierrechnungen. In der Übergangszeit gilt: Papier ist immer erlaubt, PDF u. ä. nur mit Zustimmung des Empfängers.

**Nicht zulässig für GoBD**: ZUGFeRD-Profile MINIMUM oder BASIC-WL; diese erfüllen nicht die Anforderungen an maschinelle Auswertbarkeit für steuerliche Zwecke. Mindestens **EN16931** erforderlich.

---

## Abdeckung durch dieses Werkzeug

| Anforderung | Status |
|-------------|--------|
| ZUGFeRD EN16931 Ausgangsrechnungen erzeugen | ✅ Implementiert |
| E-Rechnungen revisionssicher archivieren (DB + Dateisystem) | ✅ `zugferd_xml` in DB + `storage/xml/` |
| Unveränderbarkeit finalisierter Rechnungen | ✅ Status-Maschine |
| E-Rechnungen empfangen/importieren (Eingangsrechnungen) | ⬜ Noch nicht implementiert |
| Progressive/retrograde Prüfbarkeit für Eingangsrechnungen | ⬜ Hängt von Import ab |

---

## Quellen

- §14 UStG (Wachstumschancengesetz 2024): aktuelle Fassung unter gesetze-im-internet.de
- Forum Elektronische Steuerprüfung Newsletter (referenziert im Steuerberater-Schreiben)
- Steuerberater-Rundschreiben an Mandanten, erhalten 2026-06-11
