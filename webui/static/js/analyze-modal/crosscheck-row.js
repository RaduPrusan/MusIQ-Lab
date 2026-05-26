// Plan C Task 8: Essentia cross-check row for the reanalyze stats panel.
//
// Renders the `summary.essentia_agreement` block produced by Plan C T5 — a
// per-field comparison between the analyze pipeline's own tempo/key estimate
// and Essentia's second opinion. Visual heads-up only: a green ✓ when the two
// agree (within the server-side tolerance) and a yellow ⚠ when they disagree.
// Returns an empty string when no agreement data is available so the caller
// can safely concatenate without a null-check.

import { reformatRootedName, humanizeKeyString } from "../music/notation.js";

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// Same display pipeline as the sidebar variant (sidebar/crosscheck-card.js)
// so the two surfaces agree on accidental glyph and notation system.
function _displayKey(value, system) {
  return reformatRootedName(humanizeKeyString(value), system);
}

function icon(ok) {
  // ✓ when ok, ⚠ otherwise. Pure text, no SVG dependency.
  return ok
    ? '<span class="xcheck-icon ok" title="Essentia agrees">✓</span>'
    : '<span class="xcheck-icon warn" title="Essentia disagrees">⚠</span>';
}

// When the two estimates differ by a clean 2x ratio, the disagreement is
// almost certainly a half/double-tempo interpretation (the same beat counted
// at different metric levels). The cross-check still flags ⚠ — Plan C
// deliberately keeps raw-agreement semantics — but the UI labels the
// well-known ambiguity so the user doesn't chase a "real" disagreement.
function tempoRelationHint(analyze, essentia) {
  if (!analyze || !essentia) return '';
  const r = essentia / analyze;
  if (Math.abs(r - 0.5) < 0.05) return ' (half-tempo)';
  if (Math.abs(r - 2.0) < 0.10) return ' (double-tempo)';
  return '';
}

export function renderCrosscheckRow(agreement, notationSystem = "scientific") {
  if (!agreement || Object.keys(agreement).length === 0) return '';

  const rows = [];
  if (agreement.bpm) {
    const b = agreement.bpm;
    const hint = b.ok ? '' : tempoRelationHint(b.analyze, b.essentia);
    rows.push(
      `<div class="xcheck-row">${icon(b.ok)}` +
      `<span class="label">Tempo</span>` +
      `<span class="value">${escapeHtml(b.analyze)} vs ${escapeHtml(b.essentia)} BPM ` +
      `(Δ ${escapeHtml(b.delta)})${escapeHtml(hint)}</span></div>`,
    );
  }
  if (agreement.key) {
    const k = agreement.key;
    rows.push(
      `<div class="xcheck-row">${icon(k.ok)}` +
      `<span class="label">Key</span>` +
      `<span class="value">${escapeHtml(_displayKey(k.analyze, notationSystem))} ` +
      `vs ${escapeHtml(_displayKey(k.essentia_consensus, notationSystem))}</span></div>`,
    );
  }
  if (rows.length === 0) return '';

  return `<div class="xcheck-block"><h4>Essentia cross-check</h4>${rows.join('')}</div>`;
}
