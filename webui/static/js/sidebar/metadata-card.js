// Sidebar Metadata card — renders artist / title / release / year / ISRC
// from trackData.identify when the identifier reports identified=true.
//
// Returns an HTML string (consumed via innerHTML/<template> by the sidebar
// composer) rather than a DOM node, so the function is trivially testable
// under `node --test` without a DOM polyfill. XSS-safe: all interpolated
// values pass through escapeHtml().
//
// MusicBrainz links: when the corresponding mbid_* field is present, the
// Artist / Title / Release values become clickable links to musicbrainz.org.
// MBIDs are UUIDs from a known-safe alphabet, but they still pass through
// escapeHtml as defense-in-depth in case a corrupt identify.json injects
// something else into the field.

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function mbLink(kind, mbid, inner) {
  if (!mbid) return inner;
  const href = `https://musicbrainz.org/${kind}/${encodeURIComponent(mbid)}`;
  return `<a class="mb-link" href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer" ` +
    `title="MusicBrainz ${kind}">${inner}</a>`;
}

// Round 4 D3: trust-signaling note rendered under the card title.
// - source="fallback"           → italic "via text-match search" + tooltip with
//                                  duration variance + title similarity (from
//                                  identify.duration_variance_pct /
//                                  identify.title_similarity, formatted as
//                                  percentages with 1 decimal).
// - source="acoustid_unenriched" → italic "metadata unenriched" + tooltip
//                                  explaining the partial match.
// - source="acoustid" / "acoustid_stripped" → no note (canonical match).
// - source missing (legacy R3 caches before SCHEMA_VERSION=4) → no note;
//   treated as canonical AcoustID.
function renderSourceNote(id) {
  const source = id && id.source;
  if (source === 'fallback') {
    const variancePct = (typeof id.duration_variance_pct === 'number' &&
      Number.isFinite(id.duration_variance_pct))
      ? (id.duration_variance_pct * 100).toFixed(1) + '%'
      : 'n/a';
    const similarityPct = (typeof id.title_similarity === 'number' &&
      Number.isFinite(id.title_similarity))
      ? (id.title_similarity * 100).toFixed(1) + '%'
      : 'n/a';
    const tooltip = `via MusicBrainz text-match search&#10;` +
      `duration variance: ${variancePct}&#10;` +
      `title similarity: ${similarityPct}`;
    return `<div class="metadata-card-source-note metadata-card-source-fallback" ` +
      `title="${tooltip}">via text-match search</div>`;
  }
  if (source === 'acoustid_unenriched') {
    return `<div class="metadata-card-source-note metadata-card-source-unenriched" ` +
      `title="AcoustID matched but full metadata unavailable">metadata unenriched</div>`;
  }
  return '';
}

export function renderMetadataCard(trackData) {
  const id = trackData && trackData.identify;
  if (!id || !id.identified || !id.title) return '';

  const sourceNote = renderSourceNote(id);
  const rows = [];
  if (id.artist) {
    const inner = escapeHtml(id.artist);
    rows.push(
      `<div class="meta-row"><span class="label">Artist</span>` +
      `<span class="value">${mbLink('artist', id.mbid_artist, inner)}</span></div>`,
    );
  }
  {
    const inner = escapeHtml(id.title);
    rows.push(
      `<div class="meta-row"><span class="label">Title</span>` +
      `<span class="value">${mbLink('recording', id.mbid_recording, inner)}</span></div>`,
    );
  }
  if (id.release) {
    const inner = escapeHtml(id.release);
    rows.push(
      `<div class="meta-row"><span class="label">Release</span>` +
      `<span class="value">${mbLink('release-group', id.mbid_release_group, inner)}</span></div>`,
    );
  }
  if (id.year) {
    rows.push(
      `<div class="meta-row"><span class="label">Year</span>` +
      `<span class="value">${escapeHtml(id.year)}</span></div>`,
    );
  }
  if (id.isrc) {
    rows.push(
      `<div class="meta-row mono"><span class="label">ISRC</span>` +
      `<span class="value">${escapeHtml(id.isrc)}</span></div>`,
    );
  }

  // Provenance footer — surfaces the AcoustID match confidence so users can
  // see at a glance whether this identification was a slam-dunk match (>0.95)
  // or just-barely-above-threshold (~0.85). Plan A's threshold is 0.85 by
  // default, so anything visible here passed that bar.
  let footer = '';
  if (typeof id.acoustid_score === 'number' && Number.isFinite(id.acoustid_score)) {
    const pct = Math.round(id.acoustid_score * 100);
    footer = `<div class="meta-footer">via AcoustID · ${pct}% match</div>`;
  }

  return `<section class="sidebar-card metadata-card">` +
    `<h3>Metadata</h3>${sourceNote}${rows.join('')}${footer}</section>`;
}
