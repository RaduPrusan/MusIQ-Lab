// Tests for the Tools menu and the reanalyze modal's mode parameterization.
// Verifies the new "Analyze (rerun stale stages only)" entry routes to
// /api/tools/analyze-stale/{slug} and that the modal headings/copy adapt.

import { test } from "node:test";
import assert from "node:assert/strict";
import { JSDOM } from "jsdom";

const dom = new JSDOM("<!doctype html><html><body></body></html>");
globalThis.document = dom.window.document;
globalThis.window = dom.window;
globalThis.HTMLElement = dom.window.HTMLElement;
globalThis.Node = dom.window.Node;

// localStorage is consulted by notation-prefs imported indirectly; provide
// a minimal in-memory shim so the menus module loads cleanly.
if (!globalThis.localStorage) {
  const store = new Map();
  globalThis.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
    clear: () => store.clear(),
  };
}

test("showTools renders the new 'Analyze (rerun stale stages only)' entry between Reveal cache and Reanalyze", async () => {
  const mod = await import("../static/js/ui/menus.js");
  const overlay = mod.showTools("demo_slug", "Demo Title");
  // The Tools panel is the second child of the overlay's tree; entries are
  // direct children of the panel (after the <h2>). Filter to plain divs that
  // carry an inline style and have non-empty text — these are the entries.
  const panel = overlay.querySelector("div > div");
  // Re-read: the panel itself has multiple direct <div> children — those are
  // the entries. Skip the <h2> header and the close-button.
  const entryDivs = [...panel.children].filter(
    (n) => n.tagName === "DIV" && n.textContent.trim().length > 0,
  );
  const labels = entryDivs.map((d) => d.textContent.trim());
  const reveal = labels.findIndex((t) => /^Reveal cache/.test(t));
  const stale = labels.findIndex((t) => /^Analyze \(rerun stale stages only\)$/.test(t));
  const reanalyze = labels.findIndex((t) => /^Reanalyze \(clear cache/.test(t));
  assert.ok(reveal !== -1, `Reveal cache entry missing; labels: ${JSON.stringify(labels)}`);
  assert.ok(stale !== -1, `Analyze stale entry missing; labels: ${JSON.stringify(labels)}`);
  assert.ok(reanalyze !== -1, `Reanalyze entry missing; labels: ${JSON.stringify(labels)}`);
  assert.ok(reveal < stale, `Analyze stale must come after Reveal cache (reveal=${reveal}, stale=${stale})`);
  assert.ok(stale < reanalyze, `Analyze stale must come before Reanalyze (stale=${stale}, reanalyze=${reanalyze})`);
  overlay.remove();
});

test("Analyze-stale entry uses neutral color (not the destructive red of Reanalyze)", async () => {
  const mod = await import("../static/js/ui/menus.js");
  const overlay = mod.showTools("demo_slug", "Demo Title");
  const panel = overlay.querySelector("div > div");
  const entryDivs = [...panel.children].filter(
    (n) => n.tagName === "DIV" && n.textContent.trim().length > 0,
  );
  const staleEntry = entryDivs.find((d) => d.textContent.trim() === "Analyze (rerun stale stages only)");
  const reanalyzeEntry = entryDivs.find((d) => /^Reanalyze \(clear cache/.test(d.textContent.trim()));
  assert.ok(staleEntry, "stale entry not found");
  assert.ok(reanalyzeEntry, "reanalyze entry not found");
  // Destructive entry: explicit #ff8080.
  assert.ok(
    /#ff8080/i.test(reanalyzeEntry.style.color) || /rgb\(255, ?128, ?128\)/.test(reanalyzeEntry.style.color),
    `expected red color on Reanalyze entry, got: ${reanalyzeEntry.style.color}`,
  );
  // Neutral entry: NOT red.
  assert.ok(
    !/#ff8080/i.test(staleEntry.style.color) && !/rgb\(255, ?128, ?128\)/.test(staleEntry.style.color),
    `expected non-red color on stale entry, got: ${staleEntry.style.color}`,
  );
  overlay.remove();
});

test("clicking the Analyze-stale entry triggers a stale-mode modal that posts to /analyze-stale/", async () => {
  // ES module exports are read-only bindings, so we can't monkeypatch
  // showReanalyzeModal directly. Instead, observe the side effect: confirm
  // the resulting modal posts to the analyze-stale endpoint when its
  // confirm button is clicked.
  const calls = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      body: { getReader: () => ({ async read() { return { value: undefined, done: true }; } }) },
      async text() { return ""; },
    };
  };

  try {
    const mod = await import("../static/js/ui/menus.js");
    const toolsOverlay = mod.showTools("demo_slug", "Demo Title");
    const panel = toolsOverlay.querySelector("div > div");
    const entryDivs = [...panel.children].filter(
      (n) => n.tagName === "DIV" && n.textContent.trim().length > 0,
    );
    const staleEntry = entryDivs.find((d) => d.textContent.trim() === "Analyze (rerun stale stages only)");
    assert.ok(staleEntry, "stale entry not found");
    staleEntry.click();
    // Tools overlay is removed; the new reanalyze-modal overlay is in the body.
    // The most recent overlay added to body is the modal we want.
    const overlays = [...document.body.children].filter((n) => n.tagName === "DIV");
    const modalOverlay = overlays[overlays.length - 1];
    const heading = modalOverlay.querySelector("h2");
    // Stale-mode heading proves the right path was taken.
    assert.match(heading.textContent, /Analyze \(rerun stale stages\)/);
    // Click confirm → fetch goes to /analyze-stale/.
    const confirm = [...modalOverlay.querySelectorAll("button")].find((b) => b.textContent === "Analyze stale");
    assert.ok(confirm, "Analyze stale confirm button missing");
    confirm.click();
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/api\/tools\/analyze-stale\/demo_slug$/);
    modalOverlay.remove();
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("showReanalyzeModal({ mode: 'stale' }) confirmation pre-state shows stale heading + copy + button label", async () => {
  const mod = await import("../static/js/ui/reanalyze.js");
  const overlay = mod.showReanalyzeModal("demo_slug", "Demo Title", { mode: "stale" });
  const heading = overlay.querySelector("h2");
  assert.match(heading.textContent, /^Analyze \(rerun stale stages\) — Demo Title$/);
  // Warning copy mentions stale + preserved.
  const warn = overlay.querySelector(".reanalyze-warn");
  assert.match(warn.textContent, /stale/i);
  assert.match(warn.textContent, /preserved/i);
  // Confirm button reads "Analyze stale".
  const buttons = [...overlay.querySelectorAll("button")];
  const confirm = buttons.find((b) => b.textContent === "Analyze stale");
  assert.ok(confirm, "Confirm button must read 'Analyze stale'");
  overlay.remove();
});

test("showReanalyzeModal() default (full mode) confirmation pre-state preserves existing copy", async () => {
  const mod = await import("../static/js/ui/reanalyze.js");
  const overlay = mod.showReanalyzeModal("demo_slug", "Demo Title");
  const heading = overlay.querySelector("h2");
  assert.match(heading.textContent, /^Reanalyze — Demo Title$/);
  const buttons = [...overlay.querySelectorAll("button")];
  const confirm = buttons.find((b) => b.textContent === "Reanalyze");
  assert.ok(confirm, "Confirm button must read 'Reanalyze'");
  const warn = overlay.querySelector(".reanalyze-warn");
  assert.match(warn.textContent, /wipe/i);
  overlay.remove();
});

test("confirming a stale-mode modal posts to /api/tools/analyze-stale/{slug}, not /reanalyze/", async () => {
  // Stub fetch to capture the URL. The streamAnalyze helper consumes the
  // body; we make it look like an empty NDJSON stream that completes.
  const calls = [];
  const realFetch = globalThis.fetch;
  // Yield a single error event so finish() is called and the modal's rAF
  // ticker is stopped — otherwise the setTimeout fallback (jsdom has no rAF)
  // keeps the node:test process alive past test completion.
  const errorEvent = new TextEncoder().encode('{"type":"error","message":"test stub"}\n');
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    let yielded = false;
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      body: {
        getReader: () => ({
          async read() {
            if (!yielded) { yielded = true; return { value: errorEvent, done: false }; }
            return { value: undefined, done: true };
          },
        }),
      },
      async text() { return ""; },
    };
  };

  try {
    const mod = await import("../static/js/ui/reanalyze.js");
    const overlay = mod.showReanalyzeModal("demo_slug", "Demo Title", { mode: "stale" });
    const buttons = [...overlay.querySelectorAll("button")];
    const confirm = buttons.find((b) => b.textContent === "Analyze stale");
    assert.ok(confirm);
    confirm.click();
    // Wait one microtask tick for the async fetch chain to fire.
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(calls.length, 1, "fetch was not invoked exactly once");
    assert.match(calls[0].url, /\/api\/tools\/analyze-stale\/demo_slug$/);
    assert.equal(calls[0].init.method, "POST");
    overlay.remove();
  } finally {
    globalThis.fetch = realFetch;
  }
});

test("confirming a full-mode modal posts to /api/tools/reanalyze/{slug} (regression)", async () => {
  const calls = [];
  const realFetch = globalThis.fetch;
  // Yield a single error event so finish() is called and the modal's rAF
  // ticker is stopped — otherwise the setTimeout fallback (jsdom has no rAF)
  // keeps the node:test process alive past test completion.
  const errorEvent = new TextEncoder().encode('{"type":"error","message":"test stub"}\n');
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    let yielded = false;
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      body: {
        getReader: () => ({
          async read() {
            if (!yielded) { yielded = true; return { value: errorEvent, done: false }; }
            return { value: undefined, done: true };
          },
        }),
      },
      async text() { return ""; },
    };
  };

  try {
    const mod = await import("../static/js/ui/reanalyze.js");
    const overlay = mod.showReanalyzeModal("demo_slug", "Demo Title");
    const buttons = [...overlay.querySelectorAll("button")];
    const confirm = buttons.find((b) => b.textContent === "Reanalyze");
    assert.ok(confirm);
    confirm.click();
    await new Promise((r) => setTimeout(r, 10));
    assert.equal(calls.length, 1);
    assert.match(calls[0].url, /\/api\/tools\/reanalyze\/demo_slug$/);
    overlay.remove();
  } finally {
    globalThis.fetch = realFetch;
  }
});
