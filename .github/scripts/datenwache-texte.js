'use strict';

// Text-Datenwache fuer Issues und Pull Requests (#154): eine Stelle fuer die
// Muster, die vorher im Workflow standen. Zusatzmuster kommen aus dem
// Actions-Secret (eine Regex je Zeile, '#' beginnt einen Kommentar, Leerzeilen
// entfallen). Das Ergebnis nennt nur die Musterklasse, nie den Treffertext.

const eingebaut = [
  ['privater Schluessel', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ['IBAN-Format',         /DE\d{2} ?(?:\d{4} ?){4}\d{2}/],
  ['USt-IdNr-Format',     /(?:^|[^A-Za-z0-9])DE\d{9}(?:[^0-9]|$)/],
  ['Steuernummer-Format', /(?:^|[^0-9])\d{2,3}\/\d{3}\/\d{4,5}(?:[^0-9\/]|$)/],
];

// payload = Webhook-Payload, zusatzText = Inhalt des Secrets (kann fehlen).
// Rueckgabe: { nummer, klassen } - nummer ist die Issue-/PR-Nummer, klassen
// die getroffenen Musterklassen ohne Doppelte.
function pruefeEreignis(payload, zusatzText) {
  const p = payload || {};
  const issue = p.issue || {};
  const pull = p.pull_request || {};
  const text = [
    issue.title,
    issue.body,
    pull.title,
    pull.body,
    p.comment && p.comment.body,
    p.review && p.review.body,
  ].filter(Boolean).join('\n');
  const nummer = issue.number || pull.number;
  const zusatz = (zusatzText || '')
    .split('\n').map((z) => z.trim())
    .filter((z) => z && !z.startsWith('#'))
    .map((z) => ['Zusatzmuster', new RegExp(z)]);
  const klassen = [...new Set(
    [...eingebaut, ...zusatz].filter(([, m]) => m.test(text)).map(([k]) => k)
  )];
  return { nummer, klassen };
}

module.exports = { pruefeEreignis };
