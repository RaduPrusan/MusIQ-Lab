// Tests for the per-slug cross-check toggle state module.
//
// localStorage + document.dispatchEvent are mocked at the top of this file so
// the module can run under `node --test` without a DOM. Both APIs are simple
// enough that an in-memory polyfill covers the surface xcheck.js touches.

import { test, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

// ---- DOM polyfills ----
const _store = new Map();
globalThis.localStorage = {
  getItem: (k) => (_store.has(k) ? _store.get(k) : null),
  setItem: (k, v) => _store.set(k, String(v)),
  removeItem: (k) => _store.delete(k),
  clear: () => _store.clear(),
};

const _listeners = new Map();
globalThis.document = {
  addEventListener: (name, fn) => {
    if (!_listeners.has(name)) _listeners.set(name, new Set());
    _listeners.get(name).add(fn);
  },
  removeEventListener: (name, fn) => {
    _listeners.get(name)?.delete(fn);
  },
  dispatchEvent: (ev) => {
    for (const fn of _listeners.get(ev.type) || []) fn(ev);
    return true;
  },
};
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init) { this.type = type; this.detail = init?.detail; }
};

// Now load the module under test.
const xcheck = await import('../static/js/state/xcheck.js');
const {
  getXcheck, setXcheck, onXcheckChanged,
  activeBpm, activeKey, activeChordAnnotations,
  effectiveTrackData,
  _resetForTesting, _internals,
} = xcheck;

beforeEach(() => {
  _store.clear();
  _listeners.clear();
});

test('default state is analyze/analyze when nothing stored', () => {
  assert.deepEqual(getXcheck('any-slug'), { bpm: 'analyze', key: 'analyze' });
});

test('setXcheck persists and round-trips', () => {
  setXcheck('slug-a', { bpm: 'essentia' });
  assert.deepEqual(getXcheck('slug-a'), { bpm: 'essentia', key: 'analyze' });
  setXcheck('slug-a', { key: 'essentia' });
  assert.deepEqual(getXcheck('slug-a'), { bpm: 'essentia', key: 'essentia' });
});

test('setXcheck removes the localStorage entry when state returns to default', () => {
  setXcheck('slug-a', { bpm: 'essentia' });
  assert.equal(_store.has(`${_internals.STORAGE_PREFIX}slug-a`), true);
  setXcheck('slug-a', { bpm: 'analyze' });
  assert.equal(_store.has(`${_internals.STORAGE_PREFIX}slug-a`), false);
});

test('setXcheck dispatches musiq:xcheck-changed with slug + state', () => {
  let captured = null;
  onXcheckChanged((detail) => { captured = detail; });
  setXcheck('slug-x', { key: 'essentia' });
  assert.deepEqual(captured, { slug: 'slug-x', state: { bpm: 'analyze', key: 'essentia' } });
});

test('onXcheckChanged returns an unsubscriber', () => {
  let count = 0;
  const off = onXcheckChanged(() => { count++; });
  setXcheck('s', { bpm: 'essentia' });
  off();
  setXcheck('s', { bpm: 'analyze' });
  assert.equal(count, 1);
});

test('invalid values are ignored, not stored', () => {
  setXcheck('s', { bpm: 'WAT' });
  assert.deepEqual(getXcheck('s'), { bpm: 'analyze', key: 'analyze' });
});

test('null/undefined resets a field to default', () => {
  setXcheck('s', { bpm: 'essentia', key: 'essentia' });
  setXcheck('s', { bpm: null });
  assert.deepEqual(getXcheck('s'), { bpm: 'analyze', key: 'essentia' });
});

test('corrupt localStorage value falls back to default without throwing', () => {
  _store.set(`${_internals.STORAGE_PREFIX}s`, '{not valid json');
  assert.deepEqual(getXcheck('s'), { bpm: 'analyze', key: 'analyze' });
});

// ---- activeBpm / activeKey / activeChordAnnotations ----

test('activeBpm returns analyze value by default', () => {
  const td = {
    meta: { slug: 's', tempoBpm: 82.19 },
    essentiaAgreement: { bpm: { analyze: 82.19, essentia: 163.97, delta: 81.78, ok: false } },
  };
  assert.equal(activeBpm(td), 82.19);
});

test('activeBpm returns essentia value when toggle is set', () => {
  const td = {
    meta: { slug: 's', tempoBpm: 82.19 },
    essentiaAgreement: { bpm: { analyze: 82.19, essentia: 163.97, delta: 81.78, ok: false } },
  };
  setXcheck('s', { bpm: 'essentia' });
  assert.equal(activeBpm(td), 163.97);
});

test('activeBpm falls back to meta.tempoBpm when no agreement', () => {
  const td = { meta: { slug: 's', tempoBpm: 120.0 } };
  assert.equal(activeBpm(td), 120.0);
});

test('activeKey switches between pipeline + Essentia consensus strings', () => {
  const td = {
    meta: { slug: 's', key: 'F Major' },
    essentiaAgreement: { key: { analyze: 'F Major', essentia_consensus: 'Bb:major', ok: false } },
  };
  assert.equal(activeKey(td), 'F Major');
  setXcheck('s', { key: 'essentia' });
  assert.equal(activeKey(td), 'Bb:major');
});

test('activeChordAnnotations returns null when key toggle is analyze', () => {
  const td = {
    meta: { slug: 's' },
    chordsAltKey: { annotations: [{ roman: 'V', function: 'dominant' }] },
  };
  assert.equal(activeChordAnnotations(td), null);
});

test('activeChordAnnotations returns alt annotations when key toggle is essentia', () => {
  const td = {
    meta: { slug: 's' },
    chordsAltKey: { annotations: [{ roman: 'V', function: 'dominant' }] },
  };
  setXcheck('s', { key: 'essentia' });
  assert.deepEqual(activeChordAnnotations(td), [{ roman: 'V', function: 'dominant' }]);
});

test('activeChordAnnotations returns null when alt-key block missing', () => {
  const td = { meta: { slug: 's' } };
  setXcheck('s', { key: 'essentia' });
  assert.equal(activeChordAnnotations(td), null);
});

test('per-slug isolation: setting slug-a does not affect slug-b', () => {
  setXcheck('slug-a', { bpm: 'essentia' });
  assert.equal(getXcheck('slug-a').bpm, 'essentia');
  assert.equal(getXcheck('slug-b').bpm, 'analyze');
});

// ---- effectiveTrackData ----

const _makeTd = () => ({
  meta: { slug: 's', key: 'F Major', scale: 'F major' },
  chords: [
    { start: 0, end: 1, label: 'F:maj', roman: 'I', fn: 'tonic' },
    { start: 1, end: 2, label: 'Bb:maj', roman: 'IV', fn: 'predominant' },
  ],
  loopRoman: ['I', 'IV'],
  modalInterchange: 0,
  chordsAltKey: {
    key: 'Bb:major',
    scale: 'A♯ major',
    annotations: [
      { roman: 'V', function: 'dominant' },
      { roman: 'I', function: 'tonic' },
    ],
    loop_roman: ['V', 'I'],
    modal_interchange_count: 3,
  },
});

test('effectiveTrackData returns input unchanged when key toggle is analyze', () => {
  const td = _makeTd();
  const view = effectiveTrackData(td);
  assert.equal(view, td);  // identity, no clone needed
});

test('effectiveTrackData swaps key fields when key toggle is essentia', () => {
  const td = _makeTd();
  setXcheck('s', { key: 'essentia' });
  const view = effectiveTrackData(td);
  assert.equal(view.meta.key, 'Bb:major');
  assert.equal(view.meta.scale, 'A♯ major');
  assert.equal(view.chords[0].roman, 'V');
  assert.equal(view.chords[0].fn, 'dominant');
  assert.equal(view.chords[1].roman, 'I');
  assert.deepEqual(view.loopRoman, ['V', 'I']);
  assert.equal(view.modalInterchange, 3);
});

test('effectiveTrackData does not mutate the input', () => {
  const td = _makeTd();
  setXcheck('s', { key: 'essentia' });
  effectiveTrackData(td);
  assert.equal(td.meta.key, 'F Major');  // unchanged
  assert.equal(td.chords[0].roman, 'I');
});

test('effectiveTrackData falls back when no chordsAltKey block', () => {
  const td = { ..._makeTd(), chordsAltKey: null };
  setXcheck('s', { key: 'essentia' });
  const view = effectiveTrackData(td);
  assert.equal(view, td);  // no swap available
});

test('effectiveTrackData handles per-chord annotation length mismatch', () => {
  const td = _makeTd();
  td.chordsAltKey.annotations = [{ roman: 'V', function: 'dominant' }];  // shorter than chords
  setXcheck('s', { key: 'essentia' });
  const view = effectiveTrackData(td);
  assert.equal(view.chords[0].roman, 'V');
  // Second chord falls back to original
  assert.equal(view.chords[1].roman, 'IV');
});

test('_resetForTesting clears just the named slug', () => {
  setXcheck('a', { bpm: 'essentia' });
  setXcheck('b', { bpm: 'essentia' });
  _resetForTesting('a');
  assert.equal(getXcheck('a').bpm, 'analyze');
  assert.equal(getXcheck('b').bpm, 'essentia');
});
