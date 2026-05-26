import { test } from 'node:test';
import assert from 'node:assert/strict';

import { renderCrosscheckRow } from '../static/js/analyze-modal/crosscheck-row.js';

test('renders agreement green when ok', () => {
  const html = renderCrosscheckRow({
    bpm: { analyze: 120.0, essentia: 120.4, delta: 0.4, ok: true },
    key: { analyze: 'A:minor', essentia_consensus: 'A:minor', ok: true },
  });
  assert.ok(html.includes('120'));
  // Key values are humanized + reformatted ("A:minor" → "A minor"). Raw
  // colon form should not leak into the rendered HTML.
  assert.ok(html.includes('A minor'));
  assert.ok(!html.includes('A:minor'));
  // Some indicator that it's "ok" — checkmark, class, etc.
  assert.ok(html.includes('ok') || html.includes('✓'));
});

test('reformats key values in solfège mode', () => {
  const html = renderCrosscheckRow({
    key: { analyze: 'A:minor', essentia_consensus: 'Bb:major', ok: false },
  }, 'solfege');
  assert.ok(html.includes('La minor'));
  assert.ok(html.includes('Si♭ major'));
});

test('renders disagreement marker', () => {
  const html = renderCrosscheckRow({
    bpm: { analyze: 120.0, essentia: 60.0, delta: 60.0, ok: false },
    key: { analyze: 'A:minor', essentia_consensus: 'A:minor', ok: true },
  });
  assert.ok(html.includes('60'));
  // Some indicator that disagreement happened
  assert.ok(html.includes('warn') || html.includes('⚠'));
});

test('returns empty when agreement object is empty', () => {
  assert.equal(renderCrosscheckRow({}), '');
});

test('returns empty when agreement is missing entirely', () => {
  assert.equal(renderCrosscheckRow(undefined), '');
});

test('handles bpm-only (no key) agreement gracefully', () => {
  const html = renderCrosscheckRow({
    bpm: { analyze: 120.0, essentia: 120.0, delta: 0.0, ok: true },
  });
  assert.ok(html.includes('120'));
  assert.ok(!html.includes('A minor'));  // key row absent
});

test('labels half-tempo when essentia ≈ analyze / 2', () => {
  const html = renderCrosscheckRow({
    bpm: { analyze: 157.89, essentia: 79.93, delta: 77.96, ok: false },
  });
  assert.ok(html.includes('half-tempo'));
  assert.ok(html.includes('⚠'));  // still flagged
});

test('labels double-tempo when essentia ≈ 2 × analyze', () => {
  const html = renderCrosscheckRow({
    bpm: { analyze: 84.51, essentia: 172.27, delta: 87.76, ok: false },
  });
  assert.ok(html.includes('double-tempo'));
  assert.ok(html.includes('⚠'));
});

test('does not label small disagreements', () => {
  const html = renderCrosscheckRow({
    bpm: { analyze: 95.24, essentia: 98.70, delta: 3.46, ok: false },
  });
  assert.ok(!html.includes('half-tempo'));
  assert.ok(!html.includes('double-tempo'));
});

test('does not label when ok=true even if ratio is exactly 2x', () => {
  // Defensive: if the server-side tolerance ever flips this to ok, the hint
  // should disappear too — we only annotate the disagreement case.
  const html = renderCrosscheckRow({
    bpm: { analyze: 60.0, essentia: 120.0, delta: 60.0, ok: true },
  });
  assert.ok(!html.includes('half-tempo'));
  assert.ok(!html.includes('double-tempo'));
});
