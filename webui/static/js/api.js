// Central fetch wrapper. All JSON endpoints in the webui go through getJson,
// so 4xx/5xx responses raise a toast (see ui/toast.js) and throw a structured
// Error the caller can branch on (err.status, err.body).
//
// Note: callers that want to swallow the error silently (e.g. f0 is optional
// and a 404 is not user-actionable) can pass { silent: true }.
import { showToast } from "./ui/toast.js";

async function getJson(path, { silent = false } = {}) {
  let r;
  try {
    r = await fetch(path);
  } catch (netErr) {
    // Network-level failure (offline, DNS, server down). fetch() only rejects
    // on these — not on HTTP error statuses, those go through the !ok branch.
    if (!silent) showToast("error", `Network error: ${path}`);
    throw netErr;
  }
  if (!r.ok) {
    let body = null;
    try { body = await r.json(); } catch {}
    if (!silent) {
      const detail = body?.detail || body?.error || r.statusText || "";
      showToast("error", `Request failed (${r.status}): ${path}${detail ? ` — ${detail}` : ""}`);
    }
    const err = new Error(`${path} -> ${r.status}`);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  return r.json();
}

async function postJson(path, body, { silent = false } = {}) {
  let r;
  try {
    r = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
  } catch (netErr) {
    if (!silent) showToast("error", `Network error: ${path}`);
    throw netErr;
  }
  if (!r.ok) {
    let bodyJson = null;
    try { bodyJson = await r.json(); } catch {}
    if (!silent) {
      const detail = bodyJson?.detail || bodyJson?.error || r.statusText || "";
      showToast("error", `Request failed (${r.status}): ${path}${detail ? ` — ${detail}` : ""}`);
    }
    const err = new Error(`${path} -> ${r.status}`);
    err.status = r.status;
    err.body = bodyJson;
    throw err;
  }
  return r.json();
}

async function patchJson(path, body, { silent = false } = {}) {
  let r;
  try {
    r = await fetch(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
  } catch (netErr) {
    if (!silent) showToast("error", `Network error: ${path}`);
    throw netErr;
  }
  if (!r.ok) {
    let bodyJson = null;
    try { bodyJson = await r.json(); } catch {}
    if (!silent) {
      const detail = bodyJson?.detail || bodyJson?.error || r.statusText || "";
      showToast("error", `Request failed (${r.status}): ${path}${detail ? ` — ${detail}` : ""}`);
    }
    const err = new Error(`${path} -> ${r.status}`);
    err.status = r.status;
    err.body = bodyJson;
    throw err;
  }
  return r.json();
}

async function deleteJson(path, { silent = false } = {}) {
  let r;
  try {
    r = await fetch(path, { method: "DELETE" });
  } catch (netErr) {
    if (!silent) showToast("error", `Network error: ${path}`);
    throw netErr;
  }
  if (!r.ok) {
    let body = null;
    try { body = await r.json(); } catch {}
    if (!silent) {
      const detail = body?.detail || body?.error || r.statusText || "";
      showToast("error", `Request failed (${r.status}): ${path}${detail ? ` — ${detail}` : ""}`);
    }
    const err = new Error(`${path} -> ${r.status}`);
    err.status = r.status;
    err.body = body;
    throw err;
  }
  return r.json();
}

export const api = {
  listTracks: () => getJson("/api/tracks"),
  getSummary: (slug) => getJson(`/api/tracks/${encodeURIComponent(slug)}`),
  // Rename track — PATCH the user-authored display_name. Server splits on
  // " - " and updates lyrics/meta.json artist/title as a side effect.
  renameTrack: (slug, displayName) =>
    patchJson(`/api/tracks/${encodeURIComponent(slug)}`, { display_name: displayName }),
  // F0 is optional analysis output — a 404 here just means the stage didn't
  // run for this track, not a user-facing error. Suppress the toast.
  getF0:      (slug) => getJson(`/api/tracks/${encodeURIComponent(slug)}/f0`, { silent: true }),
  // Last.fm tags + similar artists. Soft-fails to {available: false, reason}
  // server-side when the track has no MBID or Last.fm is unreachable, so a
  // toast on 4xx/5xx would be noise — silent. (Endpoint lives at the
  // /api/track/{slug}/lastfm singular path, distinct from the /api/tracks/
  // family above.)
  getLastfm:  (slug) => getJson(`/api/track/${encodeURIComponent(slug)}/lastfm`, { silent: true }),
  audioSourceUrl: (slug) => `/api/tracks/${encodeURIComponent(slug)}/audio/source`,
  audioStemUrl:   (slug, name) => `/api/tracks/${encodeURIComponent(slug)}/audio/stem/${encodeURIComponent(name)}`,
  // Lyrics. getLyrics suppresses toast on 404 — the tab will treat null as
  // "no cache, please fetch" rather than a user-facing error.
  getLyrics:    async (slug) => {
    try { return await getJson(`/api/tracks/${encodeURIComponent(slug)}/lyrics`, { silent: true }); }
    catch (e) { if (e.status === 404) return null; throw e; }
  },
  fetchLyrics:  (slug, body = {}) => postJson(`/api/tracks/${encodeURIComponent(slug)}/lyrics/fetch`, body),
  pasteLyrics:  (slug, text) => postJson(`/api/tracks/${encodeURIComponent(slug)}/lyrics/paste`, { text }),
  deleteLyrics: (slug) => deleteJson(`/api/tracks/${encodeURIComponent(slug)}/lyrics`),
  // Chat. getChatHistory is silent because an empty conversation returning
  // {messages: []} is normal — no toast on empty/missing.
  getChatHistory: (slug) => getJson(`/api/chat/${encodeURIComponent(slug)}`, { silent: true }),
  clearChat:      (slug) => deleteJson(`/api/chat/${encodeURIComponent(slug)}`),
  chatTurnUrl:    (slug) => `/api/chat/${encodeURIComponent(slug)}/turn`,
  // Best-effort interrupt of an in-flight turn. Silent because a "no actor /
  // nothing in flight" 200 with {interrupted: false} is normal and we don't
  // want to toast the user for clicking Stop a beat too late.
  stopChat:       (slug) => postJson(`/api/chat/${encodeURIComponent(slug)}/stop`, {}, { silent: true }),
};

api.slugForFilename = async (filename) => {
  const r = await fetch(`/api/util/slug-for?filename=${encodeURIComponent(filename)}`);
  if (r.status === 415) return await r.json();
  if (!r.ok) {
    const e = new Error(`slug-for failed: ${r.status}`);
    e.status = r.status;
    throw e;
  }
  return await r.json();
};

api.youtubeDryRun = async (url, { update_ytdlp = false } = {}) => {
  const r = await fetch("/api/tools/analyze/youtube", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, dry_run: true, update_ytdlp }),
  });
  if (r.status === 503) {
    const body = await r.json();
    const e = new Error(body.message || "yt-dlp stale");
    e.kind = "ytdlp_stale";
    throw e;
  }
  if (!r.ok) {
    const body = await r.json().catch(() => ({}));
    const e = new Error(body.message || `dry_run failed: ${r.status}`);
    e.kind = body.error || "ytdlp_metadata_failed";
    throw e;
  }
  return await r.json();
};
