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

// POSIX-Klassen in JS uebersetzen (#202 Teil 1). JS kennt keine Klassen wie
// [:space:]; new RegExp("Max[[:space:]]+Muster").test("Max Muster") ist false.
// Uebersetzt wird nur das innere [:name:] innerhalb der aeusseren Klammer;
// die aeussere Klammer (und ein fuehrendes ^) bleiben unberuehrt. Eine
// unbekannte Klasse wirft, damit das Muster nicht stillschweigend versagt.
function posixNachJs(muster) {
  return muster.replace(/\[:([a-z]+):\]/g, (ganz, name) => {
    switch (name) {
      case 'space': return '\\s';
      case 'digit': return '0-9';
      case 'alpha': return 'A-Za-z\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df';
      case 'alnum': return 'A-Za-z0-9\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc\u00df';
      case 'upper': return 'A-Z\u00c4\u00d6\u00dc';
      case 'lower': return 'a-z\u00e4\u00f6\u00fc\u00df';
      case 'punct': return punctKlasse();
      default: throw new Error('unbekannte POSIX-Klasse: [:' + name + ':]');
    }
  });
}

// ASCII-Satzzeichen fuer [:punct:], innerhalb einer Klammerklasse escaped
// (], \, ^, - brauchen einen fuehrenden Backslash). Reihenfolge 33-47, 58-64,
// 91-96, 123-126.
function punctKlasse() {
  let s = '';
  const bereiche = [[33, 47], [58, 64], [91, 96], [123, 126]];
  for (const [a, b] of bereiche) {
    for (let c = a; c <= b; c++) s += String.fromCharCode(c);
  }
  return s.replace(/[\]\\^-]/g, '\\$&');
}

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
    .map((z) => ['Zusatzmuster', new RegExp(posixNachJs(z))]);
  const klassen = [...new Set(
    [...eingebaut, ...zusatz].filter(([, m]) => m.test(text)).map(([k]) => k)
  )];
  return { nummer, klassen };
}

module.exports = { pruefeEreignis, posixNachJs };
