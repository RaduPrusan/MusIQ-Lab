import { el, clear } from "./dom.js";
import { reformatRootedName } from "../music/notation.js";
import { getNotationSystem } from "../music/notation-prefs.js";

const SORT_OPTIONS = [
  { id: "recent",   label: "Recently analyzed", cmp: (a, b) => b.summary_mtime_ns - a.summary_mtime_ns },
  { id: "title",    label: "Title",             cmp: (a, b) => a.title.localeCompare(b.title) },
  { id: "key",      label: "Key",               cmp: (a, b) => a.key.localeCompare(b.key) },
  { id: "tempo",    label: "Tempo",             cmp: (a, b) => a.tempo_bpm - b.tempo_bpm },
  { id: "duration", label: "Duration",          cmp: (a, b) => a.duration_sec - b.duration_sec },
];

const HAS_VOCALS = [
  { id: "any",   label: "Any vox" },
  { id: "vocal", label: "Vocal only" },
  { id: "instr", label: "Instr only" },
];

export function filterTracks(tracks, { query = "", sort = "recent", hasVocals = "any" } = {}) {
  const q = query.trim().toLowerCase();
  const out = tracks.filter((t) => {
    if (q && !t.title.toLowerCase().includes(q) && !t.slug.includes(q)) return false;
    if (hasVocals === "vocal" && !t.has_vocals) return false;
    if (hasVocals === "instr" && t.has_vocals) return false;
    return true;
  });
  const sortDef = SORT_OPTIONS.find((s) => s.id === sort) ?? SORT_OPTIONS[0];
  return out.slice().sort(sortDef.cmp);
}

export function mountTrackPicker(picker, tracks, { currentSlug, onPick }) {
  picker.querySelector(".tp-panel")?.remove();
  picker.classList.remove("open");

  const state = { query: "", sort: "recent", hasVocals: "any" };
  let panel = null;

  const close = () => {
    picker.classList.remove("open");
    panel?.remove();
    panel = null;
    document.removeEventListener("click", clickOutside);
  };
  const clickOutside = (e) => { if (!picker.contains(e.target)) close(); };
  const open = () => {
    picker.classList.add("open");
    panel = build();
    picker.appendChild(panel);
    panel.querySelector("input").focus();
    document.addEventListener("click", clickOutside);
  };

  picker.toggle = () => (picker.classList.contains("open") ? close() : open());
  picker.close = close;

  function build() {
    const root = el("div", {
      class: "tp-panel",
      onClick: (e) => e.stopPropagation(),
    });

    root.appendChild(buildHeader(tracks.length));

    const input = el("input", { type: "text", attrs: { placeholder: "Search tracks…" } });
    input.addEventListener("input", () => { state.query = input.value; renderList(); });
    const countSpan = el("span", { class: "count", style: { fontSize: "9px", color: "var(--text-disabled)" } });
    root.appendChild(el("div", { class: "tp-search" }, [
      el("span", { style: { color: "var(--text-disabled)", fontSize: "13px" }, text: "⌕" }),
      input,
      countSpan,
    ]));

    const sortPill = pill(sortLabel(state.sort), () => { state.sort = nextOf(SORT_OPTIONS.map((s) => s.id), state.sort); sortPill.firstChild.textContent = `${sortLabel(state.sort)} `; renderList(); }, true);
    const voxPill  = pill(hasVocalsLabel(state.hasVocals), () => { state.hasVocals = nextOf(HAS_VOCALS.map((h) => h.id), state.hasVocals); voxPill.firstChild.textContent = `${hasVocalsLabel(state.hasVocals)} `; renderList(); });
    root.appendChild(el("div", { class: "tp-controls" }, [
      el("span", { class: "lbl", text: "Sort" }),
      sortPill,
      el("span", { class: "sep", style: { width: "1px", height: "14px", background: "var(--surface-3)" } }),
      el("span", { class: "lbl", text: "Filter" }),
      voxPill,
    ]));

    const list = el("div", { class: "tp-list" });
    root.appendChild(list);

    root.appendChild(el("div", { class: "tp-footer" }, [
      el("span", { text: `cache/ · ${tracks.length} tracks` }),
      el("span", { text: "↑↓ navigate · ↵ open · esc close" }),
    ]));

    function renderList() {
      const filtered = filterTracks(tracks, state);
      countSpan.textContent = `${filtered.length} of ${tracks.length}`;
      clear(list);
      for (const t of filtered) list.appendChild(rowEl(t, t.slug === currentSlug));
    }
    renderList();
    return root;
  }

  function pill(text, onClick, active = false) {
    return el("span", {
      class: `pill${active ? " active" : ""}`,
      onClick,
    }, [
      document.createTextNode(`${text} `),
      el("span", { class: "chev", text: "▾" }),
    ]);
  }

  function rowEl(t, isCurrent) {
    const subBits = [];
    if (t.warnings?.length) subBits.push(el("span", { class: "warn", text: t.warnings[0] }));

    const titleNode = el("span", { class: "title", text: t.title });
    const stale = Array.isArray(t.stale_stages) ? t.stale_stages : [];
    const headerKids = [titleNode];
    if (stale.length) {
      // Small ⟳ chip with count. Tooltip lists stage names so the user can
      // see what's actually stale without opening the modal. Click stops
      // propagation so it doesn't double-fire onPick.
      const chip = el("span", {
        class: "tp-stale-chip",
        attrs: { title: `Stale stages: ${stale.join(", ")}\nClick to re-run only these.` },
        onClick: async (e) => {
          e.stopPropagation();
          close();
          try {
            const m = await import("./reanalyze.js");
            m.showReanalyzeModal(t.slug, t.title, { mode: "stale", stages: stale });
          } catch (err) {
            console.error("[track-picker] failed to load reanalyze modal:", err);
          }
        },
      }, [
        document.createTextNode("⟳ "),
        el("span", { class: "n", text: String(stale.length) }),
      ]);
      headerKids.push(chip);
    }

    const nm = el("div", { class: "nm" }, [...headerKids, ...subBits]);
    const rowClasses = ["tp-row"];
    if (isCurrent) rowClasses.push("current");
    if (stale.length) rowClasses.push("stale");
    return el("div", {
      class: rowClasses.join(" "),
      onClick: () => { onPick?.(t); close(); },
    }, [
      nm,
      // Pretty-print the key column so accidentals render as ♯/♭ and the
      // root letter follows the user's notation preference (e.g. "F♯ minor"
      // or "Fa♯ minor"). Panel rebuilds on every open, so reading the prefs
      // at row time is enough — no notation-changed listener needed.
      el("div", { class: "k", text: reformatRootedName(t.key, getNotationSystem()) }),
      el("div", { class: "t", text: t.tempo_bpm.toFixed(1) }),
      el("div", { class: "d", text: formatDuration(t.duration_sec) }),
      el("div", { class: "ind", text: isCurrent ? "▶" : "" }),
    ]);
  }
}

function buildHeader(trackCount) {
  const header = document.createElement("div");
  header.className = "tp-header";

  const left = document.createElement("div");
  left.className = "tp-header-title";
  const label = document.createTextNode("LIBRARY · ");
  const count = document.createElement("span");
  count.className = "tp-count";
  count.textContent = String(trackCount);
  const trail = document.createTextNode(" TRACKS");
  left.appendChild(label);
  left.appendChild(count);
  left.appendChild(trail);
  header.appendChild(left);

  const actions = document.createElement("div");
  actions.className = "tp-header-actions";
  const fileBtn = document.createElement("button");
  fileBtn.className = "analyze-pill";
  fileBtn.type = "button";
  fileBtn.textContent = "Analyze file";
  fileBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      const m = await import("./analyze-modal.js");
      m.showAnalyzeModal({ mode: "file" });
    } catch (err) {
      console.error("[track-picker] failed to load analyze-modal:", err);
    }
  });
  const ytBtn = document.createElement("button");
  ytBtn.className = "analyze-pill";
  ytBtn.type = "button";
  ytBtn.textContent = "Analyze Youtube video";
  ytBtn.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      const m = await import("./analyze-modal.js");
      m.showAnalyzeModal({ mode: "youtube" });
    } catch (err) {
      console.error("[track-picker] failed to load analyze-modal:", err);
    }
  });
  actions.appendChild(fileBtn);
  actions.appendChild(ytBtn);
  header.appendChild(actions);

  return header;
}

function sortLabel(id)        { return SORT_OPTIONS.find((s) => s.id === id)?.label ?? id; }
function hasVocalsLabel(id)   { return HAS_VOCALS.find((h) => h.id === id)?.label ?? id; }
function nextOf(arr, current) { const i = arr.indexOf(current); return arr[(i + 1) % arr.length]; }
function formatDuration(sec)  {
  const m = Math.floor(sec / 60), s = Math.round(sec - m * 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}
