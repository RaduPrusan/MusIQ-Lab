// Sidebar Cross-check card — persistent tempo/key second-opinion vs Essentia.
//
// The cross-check data (summary.essentia_agreement, produced by Plan C's
// compute_agreement) was originally surfaced only in the reanalyze modal's
// post-run stats panel (see analyze-modal/crosscheck-row.js). That left the
// signal invisible during normal browsing — a track whose pipeline tempo is
// half/double the Essentia second-opinion reads as "tempo 82 BPM" with no
// hint that there's a known ambiguity. This sidebar card makes the same data
// visible whenever you're looking at the track.
//
// Same rendering contract as renderCrosscheckRow: returns "" when there's no
// agreement data, so the caller can concatenate without a null check. The
// modal-side renderer is left untouched — it has subtly different layout
// expectations (h4 inside an xcheck-block, no card chrome) than the sidebar.
//
// XSS-safe: all interpolated values pass through escapeHtml.

import { reformatRootedName, humanizeKeyString } from "../music/notation.js";

// Pretty-print a key value from the Essentia agreement block (either side
// may arrive as "Bb:major" or as the analyze pipeline's "F Major") into a
// notation-system-aware display string. Falls back to the input on empty
// input so the renderer stays composable. Pass system="scientific" or
// "solfege" — callers pull this from getNotationSystem() (or pass an
// explicit value in tests).
function _displayKey(value, system) {
  return reformatRootedName(humanizeKeyString(value), system);
}

function escapeHtml(s) {
  if (s == null) return '';
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function icon(ok) {
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

// Optional `xcheck` argument: {bpm, key} indicating which side is currently
// active per the cross-check toggle (state/xcheck.js). When the user has
// selected a non-default side and that side disagrees, we mark the chosen
// value with a small "(active)" annotation so the card stays consistent with
// the top-bar pill. Omitting xcheck preserves backward compatibility — every
// existing test passes the agreement only.
export function renderCrosscheckCard(agreement, xcheck = null, notationSystem = "scientific") {
  if (!agreement || Object.keys(agreement).length === 0) return '';

  const activeMark = (side, currentChoice) =>
    currentChoice === side ? ' <span class="xc-active">(active)</span>' : '';

  const rows = [];
  if (agreement.bpm) {
    const b = agreement.bpm;
    const hint = b.ok ? '' : tempoRelationHint(b.analyze, b.essentia);
    const aMark = xcheck && !b.ok ? activeMark('analyze',  xcheck.bpm) : '';
    const eMark = xcheck && !b.ok ? activeMark('essentia', xcheck.bpm) : '';
    rows.push(
      `<div class="xcheck-row">${icon(b.ok)}` +
      `<span class="label">Tempo</span>` +
      `<span class="value">${escapeHtml(b.analyze)}${aMark} vs ${escapeHtml(b.essentia)}${eMark} BPM ` +
      `(Δ ${escapeHtml(b.delta)})${escapeHtml(hint)}</span></div>`,
    );
  }
  if (agreement.key) {
    const k = agreement.key;
    const aMark = xcheck && !k.ok ? activeMark('analyze',  xcheck.key) : '';
    const eMark = xcheck && !k.ok ? activeMark('essentia', xcheck.key) : '';
    rows.push(
      `<div class="xcheck-row">${icon(k.ok)}` +
      `<span class="label">Key</span>` +
      `<span class="value">${escapeHtml(_displayKey(k.analyze, notationSystem))}${aMark} ` +
      `vs ${escapeHtml(_displayKey(k.essentia_consensus, notationSystem))}${eMark}</span></div>`,
    );
  }
  if (rows.length === 0) return '';

  return `<section class="sidebar-card crosscheck-card">` +
    `<h3>Cross-check</h3>${rows.join('')}</section>`;
}
