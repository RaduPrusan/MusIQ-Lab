// webui/static/js/theme/css-tokens.js
// Canvas-side reader for CSS custom properties. Subscribers re-read
// after each musiq:theme-changed event so canvas paint paths can refresh
// their cached colors / alphas without polling.

export function readToken(name) {
  return getComputedStyle(document.documentElement)
    .getPropertyValue("--" + name)
    .trim();
}

export function readAlpha(name, fallback = 1) {
  const raw = readToken(name);
  const n = parseFloat(raw);
  if (!Number.isFinite(n)) return fallback;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

export function subscribe(fn) {
  const handler = (e) => fn(e?.detail);
  document.addEventListener("musiq:theme-changed", handler);
  return () => document.removeEventListener("musiq:theme-changed", handler);
}
