/**
 * Device-picker for Settings → Audio engine → WASAPI.
 *
 * Renders a <select> populated from wasapiEngine.listDevices() plus a
 * Refresh-devices button. Selecting an entry persists the (hostapi,
 * device_name, exclusive, samplerate) identity to localStorage["musiq.audio"]
 * and pushes a set_device op over the WS. Phase 1 does not open any
 * PortAudio stream on the server side; the picker's job is to wire the
 * UI for Phase 2.
 *
 * The session-scoped device_index is NEVER persisted — only the identity
 * tuple, which is re-resolved on each page load (memory note
 * `windows_audio_device_identity`).
 */
import { el } from "../ui/dom.js";

const STORAGE_KEY = "musiq.audio";

function readStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const obj = JSON.parse(raw);
    return (obj && typeof obj === "object") ? obj : null;
  } catch {
    return null;
  }
}

function writeStored(patch) {
  const prev = readStored() || {};
  const next = { ...prev, ...patch };
  localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  return next;
}

function findStoredEntry(entries, savedDevice) {
  if (!savedDevice) return null;
  return entries.find((e) =>
    e.hostapi === savedDevice.hostapi
    && e.device_name === savedDevice.device_name
    && e.exclusive === !!savedDevice.exclusive
  ) || null;
}

export function buildDevicePicker(wasapiEngine, _options = {}) {
  const root = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", marginTop: "6px" } });
  const select = el("select", {
    style: {
      background: "var(--surface-2)",
      color: "var(--text-primary)",
      border: "1px solid var(--surface-3)",
      borderRadius: "4px",
      padding: "4px 6px",
      fontSize: "12px",
    },
  });
  const refreshBtn = el("button", {
    text: "Refresh devices",
    style: {
      background: "var(--surface-2)",
      color: "var(--text-secondary)",
      border: "1px solid var(--surface-3)",
      borderRadius: "4px",
      padding: "4px 8px",
      fontSize: "11px",
      cursor: "pointer",
      alignSelf: "flex-start",
    },
  });
  const status = el("div", {
    style: { fontSize: "11px", color: "var(--text-muted)" },
    text: "Select a device to open a stream.",
  });
  // device-status hook for Phase 5 latency display. wasapi-engine emits
  // `streamInfo` after every successful set_device → AckMsg pair; we render
  // the driver-reported numbers here.
  status.className = "device-status";
  root.appendChild(select);
  root.appendChild(refreshBtn);
  root.appendChild(status);

  // Subscribe to streamInfo so the user sees the actual output rate +
  // blocksize + latency once the device is open. Idempotent re-subscribes
  // are safe because wasapiEngine.on() uses a Set.
  if (wasapiEngine && typeof wasapiEngine.on === "function") {
    wasapiEngine.on("streamInfo", (info) => {
      if (!info) return;
      const sr = info.samplerate | 0;
      const blocks = info.blocksize | 0;
      const ms = (Number(info.output_latency_sec) * 1000).toFixed(1);
      const kHz = (sr / 1000).toFixed(sr % 1000 === 0 ? 0 : 1);
      status.textContent =
        `Output: ${kHz} kHz · ${blocks} frames · ${ms} ms buffer`;
    });
  }

  let currentEntries = [];

  function populate(entries) {
    currentEntries = entries;
    while (select.firstChild) select.removeChild(select.firstChild);
    if (!entries.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(no output devices found)";
      select.appendChild(opt);
      select.disabled = true;
      return;
    }
    select.disabled = false;
    for (const entry of entries) {
      const opt = document.createElement("option");
      opt.value = entry.id;
      opt.textContent = entry.label;
      select.appendChild(opt);
    }
    // Restore the saved selection if it still exists in this enumeration.
    const stored = readStored();
    const match = findStoredEntry(entries, stored?.device);
    if (match) {
      select.value = match.id;
    } else if (stored?.device) {
      // Saved device gone (driver upgrade, USB unplug). Phase 4 will surface
      // a toast; Phase 1 logs and falls back to the first entry visually.
      // eslint-disable-next-line no-console
      console.warn("device-picker: saved device not found in current enumeration", stored.device);
    }
  }

  async function reload({ refresh = false } = {}) {
    try {
      const list = refresh
        ? await wasapiEngine.refreshDevices()
        : await wasapiEngine.listDevices();
      populate(list);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("device-picker: failed to list devices", err);
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "(error listing devices)";
      while (select.firstChild) select.removeChild(select.firstChild);
      select.appendChild(opt);
      select.disabled = true;
    }
  }

  select.addEventListener("change", async () => {
    const entry = currentEntries.find((e) => e.id === select.value);
    if (!entry) return;
    // Persist (hostapi, device_name, exclusive, samplerate). NEVER the index.
    writeStored({
      engine: "wasapi",
      device: {
        hostapi: entry.hostapi,
        device_name: entry.device_name,
        exclusive: entry.exclusive,
        samplerate: entry.default_samplerate,
      },
    });
    try {
      await wasapiEngine.setDevice({
        hostapi: entry.hostapi,
        device_name: entry.device_name,
        exclusive: entry.exclusive,
        samplerate: entry.default_samplerate,
      });
    } catch (err) {
      // eslint-disable-next-line no-console
      console.warn("device-picker: set_device failed", err);
      return;
    }
    // Fire the engine rebuild so the new device is honored on the next
    // load. This is the same hook menus.js uses on engine-radio change —
    // the engine and the device are coupled via localStorage, so we
    // treat a device change as engine-state-changed. Restarting the
    // track is acceptable for v1 and matches the engine-swap behaviour
    // documented in main.js. Critically: without this, the engine that
    // failed its initial load (no device chosen) stays in the failed
    // state and `play` does nothing.
    if (typeof window !== "undefined" && typeof window.__musiqEngineRebuild === "function") {
      window.__musiqEngineRebuild();
    }
  });

  refreshBtn.addEventListener("click", () => reload({ refresh: true }));

  // Kick off initial population.
  reload({ refresh: false });

  return root;
}
