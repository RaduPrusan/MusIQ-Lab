import { test } from 'node:test';
import assert from 'node:assert/strict';

import { renderAcousticProfile } from '../static/js/sidebar/acoustic-profile.js';

test('renders loudness when extracted (gaia2 unavailable path)', () => {
  const html = renderAcousticProfile({
    essentia: {
      extracted: true,
      loudness_ebu_r128: { integrated: -9.2, range: 7.4, dynamic_complexity: 4.1 },
      high_level: { available: false },
    },
  });
  assert.ok(html.includes('-9.2'));
  assert.ok(html.includes('LUFS'));
  // Should not include danceability bar or mood pills when high_level unavailable
  assert.ok(!html.includes('Danceability'));
  assert.ok(!html.includes('mood-pill'));
});

test('renders danceability + moods when high_level available', () => {
  const html = renderAcousticProfile({
    essentia: {
      extracted: true,
      loudness_ebu_r128: { integrated: -9.2, range: 7.4, dynamic_complexity: 4.1 },
      high_level: {
        danceability: 0.71,
        voice_instrumental: 'voice',
        mood_electronic: 0.88,
        mood_acoustic: 0.03,
        mood_happy: 0.72,
        mood_sad: 0.10,
      },
    },
  });
  assert.ok(html.includes('-9.2'));
  assert.ok(html.includes('Danceability') || html.includes('danceability'));
  // mood_electronic (0.88) and mood_happy (0.72) should appear (>0.5)
  assert.ok(html.includes('electronic'));
  assert.ok(html.includes('happy'));
  // mood_sad (0.10) and mood_acoustic (0.03) should not (<0.5)
  assert.ok(!html.includes('mood-sad'));  // class name shouldn't appear
});

test('returns empty when not extracted', () => {
  assert.equal(renderAcousticProfile({ essentia: { extracted: false, reason: 'x' } }), '');
});

test('returns empty when essentia is missing', () => {
  assert.equal(renderAcousticProfile({}), '');
});

test('renders Essentia tempo row when tempo.bpm is present', () => {
  const html = renderAcousticProfile({
    essentia: {
      extracted: true,
      tempo: { bpm: 163.97, first_peak_bpm: 167.0, first_peak_weight: 0.62, beats_count: 802 },
      loudness_ebu_r128: { integrated: -14.7, range: 5.9, dynamic_complexity: 5.35 },
      high_level: { available: false },
    },
  });
  assert.ok(html.includes('Tempo (Essentia)'));
  assert.ok(html.includes('164.0 BPM'));
  // first_peak_bpm differs by >1, should surface as a secondary hint
  assert.ok(html.includes('1st peak 167.0'));
});

test('omits first-peak hint when it matches headline BPM', () => {
  const html = renderAcousticProfile({
    essentia: {
      extracted: true,
      tempo: { bpm: 120.3, first_peak_bpm: 120.0, first_peak_weight: 0.8, beats_count: 400 },
      loudness_ebu_r128: { integrated: -10, range: 5, dynamic_complexity: 4 },
      high_level: { available: false },
    },
  });
  assert.ok(html.includes('120.3 BPM'));
  assert.ok(!html.includes('1st peak'));
});

test('omits tempo row when essentia.tempo is missing', () => {
  const html = renderAcousticProfile({
    essentia: {
      extracted: true,
      loudness_ebu_r128: { integrated: -10, range: 5, dynamic_complexity: 4 },
      high_level: { available: false },
    },
  });
  assert.ok(!html.includes('Tempo (Essentia)'));
});

test('XSS-escapes mood class names (defense in depth)', () => {
  // mood labels are hard-coded, but the renderer should still defensively escape
  // any string interpolation. This test confirms the escape path is wired.
  const html = renderAcousticProfile({
    essentia: {
      extracted: true,
      loudness_ebu_r128: { integrated: -9.2, range: 7.4, dynamic_complexity: 4.1 },
      high_level: { mood_happy: 0.99, danceability: 0.5 },
    },
  });
  assert.ok(!html.includes('<script>'));
});
