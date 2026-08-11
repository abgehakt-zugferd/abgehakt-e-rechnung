<!--
  Danke, dass du etwas beiträgst. Die Punkte unten sind keine Schikane: Sie sind
  die Fragen, die sonst in der ersten Rückfrage kämen, und ohne die ein Beitrag
  nicht angenommen werden kann.
-->

## Worum geht es?

<!-- Ein bis drei Sätze. Bei einem Fehler: was war kaputt, was ist jetzt anders. -->

Behebt #

## Wie ist es geprüft?

<!--
  Welcher Test wird rot, wenn man die Änderung zurücknimmt? Nenne ihn beim Namen.
  Ein Beitrag ohne diese Antwort lässt sich nicht als richtig belegen, nur als
  plausibel.
-->

## Vor dem Absenden

- [ ] Ich stimme der Vereinbarung in [CLA.md](../blob/main/CLA.md) zu.
      Ohne diese Zustimmung kann der Beitrag nicht angenommen werden; der Grund
      steht in [CONTRIBUTING.md](../blob/main/CONTRIBUTING.md).
- [ ] Es gibt einen Test, der **zuerst rot war** und jetzt grün ist.
      Test zuerst, dann Code, ist in diesem Projekt Pflicht.
- [ ] Die vollständige Suite läuft durch: `docker compose exec -T app python -m pytest tests/ -q`
- [ ] Keine echten Rechnungs- oder Kundendaten in Code, Tests oder Beschreibung.
- [ ] Betrifft die Änderung das Archiv, die Statusmaschine oder das Finalisieren:
      Der Test läuft gegen echtes PostgreSQL (`pg_session`), nicht gegen Attrappen.
      Attrappentests bleiben grün, wenn eine Wache ausgehebelt wird.
