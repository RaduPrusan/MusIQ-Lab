import { test } from 'node:test';
import assert from 'node:assert/strict';

import { renderTagsSection } from '../static/js/sidebar/tags-row.js';

test('renders tag chips when available', () => {
  const html = renderTagsSection({
    available: true,
    tags: ['hip-hop', 'alternative', 'electronic'],
    similar_artists: [],
  });
  assert.ok(html.includes('hip-hop'));
  assert.ok(html.includes('alternative'));
  assert.ok(html.includes('chip'));
});

test('renders similar artists list', () => {
  const html = renderTagsSection({
    available: true,
    tags: [],
    similar_artists: [
      { name: 'Blur', match: 0.95, mbid: 'blur' },
      { name: 'Beck', match: 0.78, mbid: 'beck' },
    ],
  });
  assert.ok(html.includes('Blur'));
  assert.ok(html.includes('Beck'));
});

test('returns empty when available=false', () => {
  const html = renderTagsSection({ available: false, reason: 'no MBID' });
  assert.equal(html, '');
});

test('escapes tag names (XSS)', () => {
  const html = renderTagsSection({
    available: true,
    tags: ['<script>evil</script>'],
    similar_artists: [],
  });
  assert.ok(!html.includes('<script>'));
});

test('caps similar artists at 10', () => {
  const many = Array.from({ length: 25 }, (_, i) => ({
    name: `Artist${i}`, match: 0.9 - i * 0.01, mbid: '',
  }));
  const html = renderTagsSection({ available: true, tags: [], similar_artists: many });
  // Count list items
  const matches = html.match(/<li/g) || [];
  assert.ok(matches.length <= 10);
});

test('similar-artist names are clickable last.fm links', () => {
  const html = renderTagsSection({
    available: true,
    tags: [],
    similar_artists: [{ name: 'Bob Dylan', match: 1.0, mbid: 'xyz' }],
  });
  assert.ok(html.includes('href="https://www.last.fm/music/Bob+Dylan"'));
  assert.ok(html.includes('rel="noopener noreferrer"'));
});

test('heading reads "Similar artists" when only similar are present', () => {
  // Leonard-Cohen case: lots of similar, zero tags.
  const html = renderTagsSection({
    available: true,
    tags: [],
    similar_artists: [{ name: 'Tim Buckley', match: 0.6, mbid: '' }],
  });
  assert.ok(html.includes('<h3>Similar artists</h3>'));
});

test('heading reads "Tags" when only tags are present', () => {
  const html = renderTagsSection({
    available: true,
    tags: ['rock', 'pop'],
    similar_artists: [],
  });
  assert.ok(html.includes('<h3>Tags</h3>'));
});

test('heading reads "Tags & similar" when both are present', () => {
  const html = renderTagsSection({
    available: true,
    tags: ['rock'],
    similar_artists: [{ name: 'Beck', match: 0.5, mbid: '' }],
  });
  assert.ok(html.includes('Tags') && html.includes('similar'));
});

test('includes the "via Last.fm" attribution footer', () => {
  const html = renderTagsSection({
    available: true,
    tags: ['rock'],
    similar_artists: [],
  });
  assert.ok(html.includes('via Last.fm'));
});
