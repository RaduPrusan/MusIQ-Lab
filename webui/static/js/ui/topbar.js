import { el, clear } from "./dom.js";
import { reformatRootedName, humanizeKeyString } from "../music/notation.js";
import { getNotationSystem } from "../music/notation-prefs.js";
import { getXcheck, setXcheck } from "../state/xcheck.js";

// yt-dlp's output template appends "-<11-char id>.mp3". We classify the
// 11-char tail as a YT ID when it has high-entropy markers — a digit, an
// underscore, an internal dash, OR mixed case. The previous digit-only gate
// missed real IDs like "Jpz_gUyImhw" (no digits, but mixed case +
// underscore — clearly a YT ID). Plain English words (single case, no
// specials) still fall through and are preserved as titles. Mirrors the
// JS heuristic in static/js/data/track-data.js and the Python sites in
// webui/webui/lyrics.py + webui/webui/tracks.py.
const YT_ID_RE = /-[A-Za-z0-9_-]{11}\.mp3$/;
function _looksLikeYtIdTail(tail) {
  const body = tail.slice(1, -4);
  if (/[\d_-]/.test(body)) return true;
  return /[A-Z]/.test(body) && /[a-z]/.test(body);
}
function deriveTitle(file) {
  const m = file.match(YT_ID_RE);
  const base = (m && _looksLikeYtIdTail(m[0])) ? file.slice(0, m.index) : file.replace(/\.mp3$/, "");
  // If the result already looks human (has spaces), don't touch it.
  if (base.includes(" ")) return base;
  // Slug-derived form: "-" between word chars is the artist/title boundary
  // and renders as " - "; "_" is a word-internal separator and renders as " ".
  return base
    .replace(/(\w)-(\w)/g, "$1 - $2")
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// Render a two-state pill for the Key or BPM cross-check. When the analyze
// pipeline and Essentia agree (or there's no agreement data at all), the
// passed-in `agreement` is null and we fall back to a plain badge so the
// top-bar layout doesn't change for the agreeing-track common case.
//
// Spec: clicking the inactive side flips xcheck state for the current slug.
// musiq:xcheck-changed propagates downstream — the sidebar re-mounts and
// every renderer pulls fresh values from active*() helpers.
function _xcheckPill({ kind, slug, agreement, analyzeText, essentiaText, currentChoice }) {
  // No agreement (ok=true or absent) → render a plain badge with the analyze
  // value. Keeps the top-bar visually quiet when there's nothing to choose.
  if (!agreement) return badge(kind, analyzeText);

  const pill = el("span", {
    class: `badge ${kind} xc-pill`,
    attrs: { title: "Click to switch · analyze pipeline vs Essentia 2nd opinion" },
  });
  const mkSegment = (side, text) => {
    const active = currentChoice === side;
    const seg = el("span", {
      class: `xc-seg xc-seg-${side}${active ? " active" : ""}`,
      attrs: { title: side === "analyze" ? "analyze pipeline" : "Essentia 2nd opinion" },
      text,
      onClick: (e) => {
        e.stopPropagation();
        if (active) return;  // already selected
        setXcheck(slug, { [kind === "k" ? "key" : "bpm"]: side });
      },
    });
    return seg;
  };
  pill.appendChild(mkSegment("analyze", analyzeText));
  pill.appendChild(mkSegment("essentia", essentiaText));
  return pill;
}

export function mountTopbar(host, summary, { onPickerToggle, slug = null }) {
  clear(host);

  const titleSpan = el("span", {
    class: "title",
    text: summary?.track
      ? (summary.track.display_name || deriveTitle(summary.track.file))
      : "(no track)",
  });
  const chev = el("span", { class: "chev", text: "▾" });
  const picker = el("div", {
    class: "track-picker",
    id: "track-picker",
    onClick: (e) => { e.stopPropagation(); onPickerToggle?.(picker); },
  }, [titleSpan, chev]);
  host.appendChild(picker);

  if (summary?.track) {
    // Pencil → opens the rename modal. Lazy-imported on click so users who
    // never rename pay no startup cost. e.stopPropagation so the click doesn't
    // bubble to the picker (which would toggle the dropdown).
    const editBtn = el("button", {
      class: "title-edit",
      attrs: { type: "button", title: "Rename track" },
      text: "✎",
      onClick: (e) => {
        e.stopPropagation();
        import("./rename-modal.js").then((m) => m.showRenameModal({
          slug: window.__currentSlug,
          currentName: summary.track.display_name || deriveTitle(summary.track.file),
          onSaved: (resp) => {
            titleSpan.textContent = resp.display_name;
            document.title = `${resp.display_name} — MusIQ-Lab`;
            // Pass the smart-split artist/title so the lyrics-tab header
            // updates immediately (no roundtrip). When the tab hasn't loaded
            // yet, the hook falls back to a lazy-load.
            window.__musiqLyricsRefreshMeta?.({ artist: resp.artist, title: resp.title });
            // Mirror the new title into the cached /api/tracks list so the
            // picker dropdown reflects the rename next time it opens.
            // Without this, only a full page reload re-fetches the list.
            window.__musiqUpdateTrackTitle?.(window.__currentSlug, resp.display_name);
          },
        }));
      },
    });
    host.appendChild(editBtn);

    const system = getNotationSystem();
    const xc = slug ? getXcheck(slug) : { bpm: "analyze", key: "analyze" };
    const agreement = summary.essentia_agreement || null;

    // ---- Key badge (toggle when key.ok=false, plain badge otherwise) ----
    // humanizeKeyString collapses the Essentia consensus "Bb:major" form
    // into "Bb major" first; reformatRootedName then prettifies the
    // accidental ("Bb major" → "B♭ major"), matching the analyze side.
    const keyAgreement = (agreement?.key && agreement.key.ok === false) ? agreement.key : null;
    const keyAnalyzeText = reformatRootedName(
      humanizeKeyString(keyAgreement?.analyze ?? summary.track.key),
      system,
    );
    const keyEssentiaText = keyAgreement
      ? reformatRootedName(humanizeKeyString(keyAgreement.essentia_consensus), system)
      : "";
    host.appendChild(_xcheckPill({
      kind: "k", slug, agreement: keyAgreement, currentChoice: xc.key,
      analyzeText: keyAnalyzeText, essentiaText: keyEssentiaText,
    }));

    // ---- Tempo badge (toggle when bpm.ok=false, plain badge otherwise) ----
    const bpmAgreement = (agreement?.bpm && agreement.bpm.ok === false) ? agreement.bpm : null;
    const bpmAnalyzeText = `${(bpmAgreement?.analyze ?? summary.track.tempo_bpm).toFixed(1)} BPM`;
    const bpmEssentiaText = bpmAgreement
      ? `${bpmAgreement.essentia.toFixed(1)} BPM`
      : "";
    host.appendChild(_xcheckPill({
      kind: "t", slug, agreement: bpmAgreement, currentChoice: xc.bpm,
      analyzeText: bpmAnalyzeText, essentiaText: bpmEssentiaText,
    }));

    // Scale: tracks the active key. When the user toggles to Essentia, we
    // pull from summary.chords_alt_key.scale (written by alt_key.py) instead
    // of summary.analysis.scale. Time signature is key-independent.
    const scaleRaw = (xc.key === "essentia" && summary.chords_alt_key?.scale)
      ? summary.chords_alt_key.scale
      : (summary.analysis?.scale ?? "");
    const scaleHead = reformatRootedName(scaleRaw, system);
    const scaleText = `${scaleHead} · ${summary.track.time_signature ?? ""}`;
    host.appendChild(badge("s", scaleText.trim()));
    // Stem-separation quality preset (fast/normal/best). Older summaries
    // predating this provenance field have it null/undefined — skip the badge
    // rather than render "q: undefined".
    const stemsQuality = summary.provenance?.stems_quality;
    if (stemsQuality) {
      host.appendChild(badge("q", `stems: ${stemsQuality}`));
    }
  }

  const menu = el("div", { class: "menu" }, [
    el("div", { class: "item", data: { act: "tools" }, text: "⚒ Tools",
      onClick: () => import("./menus.js").then((m) => m.showTools(
        window.__currentSlug,
        summary?.track ? (summary.track.display_name || deriveTitle(summary.track.file)) : window.__currentSlug,
      )) }),
    el("div", { class: "item", data: { act: "settings" }, text: "⚙ Settings",
      onClick: () => import("./menus.js").then((m) => m.showSettings()) }),
    el("div", { class: "sep" }),
    el("div", { class: "item icon-only", data: { act: "help" }, attrs: { title: "Keyboard shortcuts" }, text: "?",
      onClick: () => import("./shortcuts.js").then((m) => m.showShortcutsModal()) }),
  ]);
  host.appendChild(menu);

  return { picker };
}

function badge(kind, text) {
  return el("span", { class: `badge ${kind}`, text });
}
