'use strict';

// Tests fuer die Text-Datenwache (#154). Werte im Format USt-IdNr., Steuer-
// nummer und IBAN werden zur Laufzeit zusammengesetzt, nie als Literal
// (dieselbe Regel wie in .githooks/test_datenwache.sh).

const test = require('node:test');
const assert = require('node:assert');
const { pruefeEreignis, posixNachJs } = require('./datenwache-texte.js');

// Erfundene Werte: echt aussehend, aber reine Probe.
const _ust_probe = () => 'DE' + '815739204';
const _steuer_probe = () => ['21', '815', '00042'].join('/');
const _iban_probe = () => ['DE' + '20', '3700', '0444', '0520', '1100', '17'].join(' ');
const _key_probe = () => '-----BEGIN ' + 'PROBE PRIVATE KEY-----';

test('PR-Titel mit USt-IdNr-Format wird erkannt', () => {
  const { nummer, klassen } = pruefeEreignis(
    { pull_request: { number: 7, title: 'probe ' + _ust_probe() + ' ende', body: 'harmlos' } },
    '');
  assert.strictEqual(nummer, 7);
  assert.ok(klassen.includes('USt-IdNr-Format'));
});

test('PR-Beschreibung mit IBAN-Format wird erkannt', () => {
  const { nummer, klassen } = pruefeEreignis(
    { pull_request: { number: 12, title: 'probe', body: 'Konto ' + _iban_probe() + ' ende' } },
    '');
  assert.strictEqual(nummer, 12);
  assert.ok(klassen.includes('IBAN-Format'));
});

test('Review-Text mit Steuernummer-Format wird erkannt', () => {
  const { nummer, klassen } = pruefeEreignis(
    { pull_request: { number: 3, title: 'probe' }, review: { body: 'Steuer ' + _steuer_probe() + ' ende' } },
    '');
  assert.strictEqual(nummer, 3);
  assert.ok(klassen.includes('Steuernummer-Format'));
});

test('Review-Kommentar mit privatem Schluessel wird erkannt', () => {
  const { nummer, klassen } = pruefeEreignis(
    { pull_request: { number: 5, title: 'probe' }, comment: { body: _key_probe() } },
    '');
  assert.strictEqual(nummer, 5);
  assert.ok(klassen.includes('privater Schluessel'));
});

test('Issue mit Treffern in Titel und Text wird erkannt, Klassen ohne Doppelte', () => {
  const { nummer, klassen } = pruefeEreignis(
    { issue: { number: 42, title: 'probe ' + _ust_probe(), body: 'nochmal ' + _ust_probe() } },
    '');
  assert.strictEqual(nummer, 42);
  assert.deepEqual(klassen, ['USt-IdNr-Format']);
});

test('Zusatzmuster aus dem Secret greifen, Kommentar- und Leerzeilen nicht', () => {
  const { klassen } = pruefeEreignis(
    { issue: { number: 8, title: 'probe', body: 'Erwaehnung Probe-Klarname' } },
    '# Kommentar\n\nProbe-Klarname\n');
  assert.deepEqual(klassen, ['Zusatzmuster']);
});

test('Sauberer Text ergibt leere Klassen', () => {
  const { nummer, klassen } = pruefeEreignis(
    { issue: { number: 9, title: 'probe Titel', body: 'harmloser Text, Betrag 24,30 Euro' } },
    'Probe-Klarname');
  assert.strictEqual(nummer, 9);
  assert.deepEqual(klassen, []);
});

test('Ergebnis enthaelt nie den Treffertext', () => {
  const wert = _iban_probe();
  const erg = pruefeEreignis(
    { pull_request: { number: 2, title: 'probe', body: 'Konto ' + wert } },
    '');
  assert.ok(erg.klassen.length > 0);
  assert.ok(!JSON.stringify(erg).includes(wert));
  assert.ok(!JSON.stringify(erg).includes(wert.split(' ').join('')));
});

// Issue #202 Teil 1: POSIX-Klassen in Zusatzmustern treffen auf GitHub nie,
// weil JS keine POSIX-Klassen kennt. posixNachJs uebersetzt das innere
// [:name:] innerhalb einer aeusseren Klammer; die aeussere Klammer bleibt.

test('Zusatzmuster mit [:space:] trifft "Max Muster" im Issue-Titel', () => {
  const { klassen } = pruefeEreignis(
    { issue: { number: 1, title: 'Max Muster', body: '' } },
    'Max[[:space:]]+Muster');
  assert.deepEqual(klassen, ['Zusatzmuster']);
});

test('Zusatzmuster mit [:digit:] und [:alpha:] trifft "123-ab"', () => {
  const { klassen } = pruefeEreignis(
    { issue: { number: 2, title: '123-ab', body: '' } },
    '[[:digit:]]{3}-[[:alpha:]]{2}');
  assert.deepEqual(klassen, ['Zusatzmuster']);
});

test('Wortgrenzen-Muster mit [^[:alpha:]] trifft Hugo nur als eigenes Wort', () => {
  const muster = '(^|[^[:alpha:]])Hugo([^[:alpha:]]|$)';
  const trifft = (titel) => pruefeEreignis(
    { issue: { number: 3, title: titel, body: '' } }, muster).klassen;
  assert.deepEqual(trifft('Herr Hugo kam'), ['Zusatzmuster']);
  assert.deepEqual(trifft('Hugobert'), []);
  assert.deepEqual(trifft('Brhugo'), []);
  assert.deepEqual(trifft('\u00c4Hugo'), []);  // Umlaut direkt vor dem Namen
});

test('posixNachJs laesst Muster ohne POSIX-Klasse unverändert', () => {
  assert.strictEqual(posixNachJs('Max[ ]+Muster'), 'Max[ ]+Muster');
  assert.strictEqual(posixNachJs(' Probe-Klarname '), ' Probe-Klarname ');
});

test('posixNachJs wirft bei unbekannter Klasse', () => {
  assert.throws(() => posixNachJs('[[:unbekannt:]]'), /unbekannte POSIX-Klasse/);
});
