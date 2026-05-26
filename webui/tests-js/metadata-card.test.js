import { test } from 'node:test';
import assert from 'node:assert/strict';

import { renderMetadataCard } from '../static/js/sidebar/metadata-card.js';

test('renders canonical title + artist when identified', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'Silent Running',
      artist: 'Gorillaz',
      release: 'Gorillaz',
      year: 2001,
      isrc: 'GBAYE0100001',
    },
  });
  assert.ok(html.includes('Silent Running'));
  assert.ok(html.includes('Gorillaz'));
  assert.ok(html.includes('2001'));
});

test('returns empty string when not identified', () => {
  const html = renderMetadataCard({
    identify: { identified: false, reason: 'no match' },
  });
  assert.equal(html, '');
});

test('returns empty string when identify is missing', () => {
  const html = renderMetadataCard({});
  assert.equal(html, '');
});

test('escapes html in title (XSS guard)', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: '<script>alert(1)</script>',
      artist: 'Safe',
    },
  });
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
});

test('renders MusicBrainz link for artist when mbid_artist present', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'Silent Running',
      artist: 'Gorillaz',
      mbid_artist: '11111111-2222-3333-4444-555555555555',
    },
  });
  assert.ok(html.includes('musicbrainz.org/artist/'));
  assert.ok(html.includes('11111111-2222-3333-4444-555555555555'));
  assert.ok(html.includes('rel="noopener noreferrer"'));
});

test('renders MB recording + release-group links when MBIDs present', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'Silent Running',
      artist: 'Gorillaz',
      release: 'Gorillaz',
      mbid_recording: 'rec-mbid-1',
      mbid_release_group: 'rg-mbid-2',
    },
  });
  assert.ok(html.includes('musicbrainz.org/recording/rec-mbid-1'));
  assert.ok(html.includes('musicbrainz.org/release-group/rg-mbid-2'));
});

test('omits MB link when corresponding mbid is missing', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'Untagged Track',
      artist: 'No MBID Artist',
      // No mbid_* fields at all.
    },
  });
  assert.ok(!html.includes('musicbrainz.org'));
  // Plain text artist still appears.
  assert.ok(html.includes('No MBID Artist'));
});

test('renders AcoustID confidence footer when score is present', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'Track',
      artist: 'Artist',
      acoustid_score: 0.978,
    },
  });
  assert.ok(html.includes('via AcoustID'));
  assert.ok(html.includes('98%'));
});

test('omits AcoustID footer when score is missing', () => {
  const html = renderMetadataCard({
    identify: { identified: true, title: 'T', artist: 'A' },
  });
  assert.ok(!html.includes('via AcoustID'));
});

// Round 4 D3: trust-signaling source note.

test('source=fallback renders italic note with class + tooltip', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: "Love's a Stranger",
      artist: 'Warhaus',
      source: 'fallback',
      duration_variance_pct: 0.013,
      title_similarity: 0.94,
    },
  });
  assert.ok(html.includes('metadata-card-source-note'));
  assert.ok(html.includes('metadata-card-source-fallback'));
  assert.ok(html.includes('via text-match search'));
  // Tooltip content
  assert.ok(html.includes('via MusicBrainz text-match search'));
  assert.ok(html.includes('&#10;'));
});

test('source=fallback tooltip formats variance + similarity as percentages with 1 decimal', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'T',
      artist: 'A',
      source: 'fallback',
      duration_variance_pct: 0.013,
      title_similarity: 0.94,
    },
  });
  assert.ok(html.includes('duration variance: 1.3%'));
  assert.ok(html.includes('title similarity: 94.0%'));
  // Make sure raw fractions are NOT leaking into the tooltip.
  assert.ok(!html.includes('0.013'));
  assert.ok(!html.includes('0.94'));
});

test('source=fallback handles missing variance/similarity gracefully', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'T',
      artist: 'A',
      source: 'fallback',
      // No duration_variance_pct / title_similarity — older fallback caches
      // or a partial sidecar still get a note (we never want to crash).
    },
  });
  assert.ok(html.includes('metadata-card-source-fallback'));
  assert.ok(html.includes('via text-match search'));
});

test('source=acoustid_unenriched renders distinct note + tooltip', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'Some Track',
      artist: 'Some Artist',
      source: 'acoustid_unenriched',
    },
  });
  assert.ok(html.includes('metadata-card-source-note'));
  assert.ok(html.includes('metadata-card-source-unenriched'));
  assert.ok(html.includes('metadata unenriched'));
  assert.ok(html.includes('AcoustID matched but full metadata unavailable'));
  // Distinct from fallback note.
  assert.ok(!html.includes('metadata-card-source-fallback'));
  assert.ok(!html.includes('via text-match search'));
});

test('source=acoustid renders no source note (canonical)', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'Canonical Track',
      artist: 'Canonical Artist',
      source: 'acoustid',
    },
  });
  assert.ok(!html.includes('metadata-card-source-note'));
  assert.ok(!html.includes('via text-match search'));
  assert.ok(!html.includes('metadata unenriched'));
});

test('source=acoustid_stripped renders no source note (canonical-via-stripped)', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'Track',
      artist: 'Artist',
      source: 'acoustid_stripped',
    },
  });
  assert.ok(!html.includes('metadata-card-source-note'));
});

test('missing source field renders no note (legacy R3 cache compat)', () => {
  const html = renderMetadataCard({
    identify: {
      identified: true,
      title: 'Legacy Track',
      artist: 'Legacy Artist',
      // No `source` field at all — old caches predate SCHEMA_VERSION=4.
    },
  });
  assert.ok(!html.includes('metadata-card-source-note'));
});
