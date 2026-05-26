// webui/static/js/theme/derive.js
// Accent token derivation. Spec §"Accent derivation".

export function hexToRgb(hex) {
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) h = h.split("").map((c) => c + c).join("");
  if (h.length !== 6) return null;
  const n = parseInt(h, 16);
  return { r: (n >> 16) & 0xff, g: (n >> 8) & 0xff, b: n & 0xff };
}

// WCAG 2.2 §1.4.3 relative luminance.
export function relativeLuminance({ r, g, b }) {
  const channel = (c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

function contrastRatio(rgbA, rgbB) {
  const lA = relativeLuminance(rgbA);
  const lB = relativeLuminance(rgbB);
  const [hi, lo] = lA > lB ? [lA, lB] : [lB, lA];
  return (hi + 0.05) / (lo + 0.05);
}

const DARK_PICK  = "#1a1a25";
const LIGHT_PICK = "#ffffff";

export function deriveAccentOn(accentHex) {
  const a = hexToRgb(accentHex);
  if (!a) return DARK_PICK;
  const cDark  = contrastRatio(a, hexToRgb(DARK_PICK));
  const cLight = contrastRatio(a, hexToRgb(LIGHT_PICK));
  // Tie-break to DARK_PICK to preserve the established Classic Dark visual.
  return cDark >= cLight ? DARK_PICK : LIGHT_PICK;
}

export function deriveAccentEmphasis(accentHex) {
  return `color-mix(in srgb, ${accentHex} 92%, #ffffff 8%)`;
}
