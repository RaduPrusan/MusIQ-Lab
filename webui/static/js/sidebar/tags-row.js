// Sidebar Last.fm card — tag chips + similar-artists list.
//
// Heading adapts to what's actually present: "Tags" when only tags, "Similar
// artists" when only similar, "Tags & similar" when both. The "via Last.fm"
// attribution footer surfaces the data source — these are crowd-sourced, not
// pipeline-derived, and live in a different mental category from the
// Metadata / Acoustic Profile / Cross-check cards above.
//
// Similar-artist names link to last.fm's artist page (URL form
// /music/<artist-name> with spaces as +). We don't currently link to
// MusicBrainz via the MBID even though we have it, because Last.fm's page
// has discography + listening data which is what users will actually want.

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const MAX_TAGS = 12;
const MAX_SIMILAR = 10;

function lastfmArtistUrl(name) {
  // Last.fm's artist URL form is /music/<name> with spaces → +. encodeURIComponent
  // handles the rest; we just swap %20 → + to match their canonical form.
  const enc = encodeURIComponent(name).replace(/%20/g, '+');
  return `https://www.last.fm/music/${enc}`;
}

export function renderTagsSection(lastfm) {
  if (!lastfm || !lastfm.available) return '';

  const sections = [];

  const tags = (lastfm.tags || []).slice(0, MAX_TAGS);
  const hasTags = tags.length > 0;
  if (hasTags) {
    const chips = tags.map(t => `<span class="chip">${escapeHtml(t)}</span>`).join('');
    sections.push(`<div class="tags-row">${chips}</div>`);
  }

  const similar = (lastfm.similar_artists || []).slice(0, MAX_SIMILAR);
  const hasSimilar = similar.length > 0;
  if (hasSimilar) {
    const items = similar.map(a => {
      const name = escapeHtml(a.name);
      const href = escapeHtml(lastfmArtistUrl(a.name));
      return (
        `<li><a class="lastfm-link" href="${href}" target="_blank" rel="noopener noreferrer">` +
        `<span class="name">${name}</span></a>` +
        `<span class="match">${Math.round((a.match || 0) * 100)}%</span></li>`
      );
    }).join('');
    sections.push(`<ul class="similar-artists">${items}</ul>`);
  }

  if (sections.length === 0) return '';

  // Heading adapts to what's actually being shown. The "& similar" form is
  // kept lowercase deliberately — the .sidebar-card h3 rule uppercases via
  // text-transform, so authoring lowercase keeps the source readable.
  const heading = hasTags && hasSimilar ? 'Tags &amp; similar'
                : hasTags                 ? 'Tags'
                                          : 'Similar artists';

  return `<section class="sidebar-card lastfm-card">` +
    `<h3>${heading}</h3>${sections.join('')}` +
    `<div class="lastfm-attribution">via Last.fm</div>` +
    `</section>`;
}
