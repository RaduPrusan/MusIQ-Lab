// webui/static/js/theme/apply.js
// Writes a token map onto documentElement.style. Order-independent and
// idempotent. Does no validation — that's store.js's job.

export function applyTheme(tokens) {
  const r = document.documentElement;
  for (const [k, v] of Object.entries(tokens)) {
    r.style.setProperty("--" + k, v);
  }
}
