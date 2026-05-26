// Sidebar Acoustic Profile card — renders Essentia-derived tempo, loudness,
// dynamic range/complexity, and (when gaia2 high-level descriptors are
// available) danceability + mood pills from trackData.essentia.
//
// Returns an HTML string (consumed via innerHTML/<template> by the sidebar
// composer) rather than a DOM node, so the function is trivially testable
// under `node --test` without a DOM polyfill. XSS-safe: all interpolated
// values pass through escapeHtml().
//
// Reality note (Plan C Task 7): the high-level SVM models depend on `gaia2`,
// which isn't on PyPI. So `high_level.available === false` is the steady-state
// today — the card degrades gracefully to tempo + loudness and skips the
// Danceability row + mood pills. When/if gaia2 lands and the stage emits
// real descriptors, the same renderer surfaces them with no further changes.

function escapeHtml(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

const MOOD_THRESHOLD = 0.5;
const MOOD_LABELS = {
  mood_acoustic: 'acoustic',
  mood_electronic: 'electronic',
  mood_happy: 'happy',
  mood_sad: 'sad',
};

function moodPills(highLevel) {
  if (!highLevel || highLevel.available === false) return '';
  const pills = [];
  for (const [key, label] of Object.entries(MOOD_LABELS)) {
    const val = Number(highLevel[key] || 0);
    if (val >= MOOD_THRESHOLD) {
      pills.push(
        `<span class="mood-pill mood-${escapeHtml(label)}" title="${val.toFixed(2)}">` +
        `${escapeHtml(label)}</span>`,
      );
    }
  }
  return pills.length ? `<div class="mood-pills">${pills.join('')}</div>` : '';
}

function danceabilityRow(highLevel) {
  if (!highLevel || highLevel.available === false) return '';
  // Only render the bar when the value is defined (don't show 0% when missing).
  if (highLevel.danceability == null) return '';
  const pct = Math.round(Number(highLevel.danceability) * 100);
  return `<div class="meta-row"><span class="label">Danceability</span>` +
    `<span class="value">` +
    `<span class="bar"><span class="bar-fill" style="width:${pct}%"></span></span>` +
    `<span class="bar-pct">${pct}%</span>` +
    `</span></div>`;
}

// Essentia's second-opinion tempo. We surface it alongside loudness even when
// the analyze pipeline's own BPM is what the rest of the UI uses, because
// disagreements (especially half/double-tempo) are common and a second number
// makes the ambiguity visible. The first-peak BPM is shown only when it
// meaningfully differs from the headline value — otherwise the row gets noisy
// without telling you anything new.
function tempoRow(tempo) {
  if (!tempo || typeof tempo.bpm !== 'number' || !Number.isFinite(tempo.bpm)) return '';
  const bpm = tempo.bpm;
  const fp = typeof tempo.first_peak_bpm === 'number' && Number.isFinite(tempo.first_peak_bpm)
    ? tempo.first_peak_bpm : null;
  const showFp = fp !== null && Math.abs(fp - bpm) >= 1.0;
  const suffix = showFp
    ? `<span class="secondary"> · 1st peak ${escapeHtml(fp.toFixed(1))}</span>`
    : '';
  return `<div class="meta-row"><span class="label">Tempo (Essentia)</span>` +
    `<span class="value">${escapeHtml(bpm.toFixed(1))} BPM${suffix}</span></div>`;
}

export function renderAcousticProfile(trackData) {
  const e = trackData && trackData.essentia;
  if (!e || !e.extracted) return '';

  const lufs = e.loudness_ebu_r128 || {};
  const hl = e.high_level || {};

  const rows = [];

  rows.push(tempoRow(e.tempo));

  if (lufs.integrated != null) {
    rows.push(
      `<div class="meta-row"><span class="label">Loudness</span>` +
      `<span class="value">${escapeHtml(lufs.integrated.toFixed(1))} LUFS</span></div>`,
    );
  }
  if (lufs.range != null) {
    rows.push(
      `<div class="meta-row"><span class="label">Range</span>` +
      `<span class="value">${escapeHtml(lufs.range.toFixed(1))} LU</span></div>`,
    );
  }
  if (lufs.dynamic_complexity != null) {
    rows.push(
      `<div class="meta-row"><span class="label">Dyn. complexity</span>` +
      `<span class="value">${escapeHtml(lufs.dynamic_complexity.toFixed(2))}</span></div>`,
    );
  }

  const dance = danceabilityRow(hl);
  const moods = moodPills(hl);

  const rowsJoined = rows.filter(Boolean).join('');
  if (!rowsJoined && !dance && !moods) return '';

  return `<section class="sidebar-card acoustic-profile">` +
    `<h3>Acoustic Profile</h3>` +
    rowsJoined + dance + moods +
    `</section>`;
}
