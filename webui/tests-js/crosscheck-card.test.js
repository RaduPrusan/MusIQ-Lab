// Tests for the sidebar variant of the cross-check renderer (crosscheck-card.js).
// The reanalyze-modal variant (crosscheck-row.js) has its own test file —
// these two renderers share data contracts but differ in DOM wrapping.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { renderCrosscheckCard } from '../static/js/sidebar/crosscheck-card.js';

test('wraps output in sidebar-card markup when data is present', () => {
  const html = renderCrosscheckCard({
    bpm: { analyze: 120.0, essentia: 120.4, delta: 0.4, ok: true },
    key: { analyze: 'A:minor', essentia_consensus: 'A:minor', ok: true },
  });
  assert.ok(html.includes('class="sidebar-card crosscheck-card"'));
  assert.ok(html.includes('<h3>Cross-check</h3>'));
  assert.ok(html.includes('120'));
  // Key values are humanized + reformatted ("A:minor" → "A minor"). The raw
  // colon form must not leak through.
  assert.ok(html.includes('A minor'));
  assert.ok(!html.includes('A:minor'));
  assert.ok(html.includes('✓'));
});

test('renders disagreement marker on each disagreeing row', () => {
  const html = renderCrosscheckCard({
    bpm: { analyze: 82.19, essentia: 163.97, delta: 81.78, ok: false },
    key: { analyze: 'F Major', essentia_consensus: 'Bb:major', ok: false },
  });
  assert.ok(html.includes('⚠'));
  assert.ok(html.includes('half-tempo') || html.includes('double-tempo'));
  // Accidentals are pretty-printed in the key row.
  assert.ok(html.includes('B♭ major'));
});

test('reformats key values in solfège mode when notationSystem="solfege"', () => {
  const html = renderCrosscheckCard({
    key: { analyze: 'F Major', essentia_consensus: 'Bb:major', ok: false },
  }, null, 'solfege');
  assert.ok(html.includes('Fa Major') || html.includes('Fa major'));
  assert.ok(html.includes('Si♭ major'));
});

test('returns empty string when agreement is empty', () => {
  assert.equal(renderCrosscheckCard({}), '');
});

test('returns empty string when agreement is null/undefined', () => {
  assert.equal(renderCrosscheckCard(null), '');
  assert.equal(renderCrosscheckCard(undefined), '');
});

test('renders bpm-only agreement without key row', () => {
  const html = renderCrosscheckCard({
    bpm: { analyze: 120.0, essentia: 120.0, delta: 0.0, ok: true },
  });
  assert.ok(html.includes('Tempo'));
  assert.ok(!html.includes('Key</span>'));
});
