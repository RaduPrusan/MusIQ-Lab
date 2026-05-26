// webui/tests-e2e/scripts/merge-verdicts.js
// Aggregates per-preset verdict files into a single visual-review/verdict.json.
// Run from webui/tests-e2e/ after `npx playwright test visual-review.spec.js`.
import fs from "fs";
import path from "path";

const OUT_ROOT = path.join("visual-review");
const PRESETS = ["classic-dark", "midnight", "studio-light", "high-contrast"];

const merged = {
  iteration: parseInt(process.env.MUSIQ_ITER || "0", 10),
  passed: true,
  summary: "",
  presets_tested: [],
  issues: [],
  screenshots: [],
  notes: "",
};

for (const p of PRESETS) {
  const vp = path.join(OUT_ROOT, `verdict-${p}.json`);
  if (!fs.existsSync(vp)) {
    merged.notes += `missing per-preset verdict for ${p}; `;
    continue;
  }
  try {
    const v = JSON.parse(fs.readFileSync(vp, "utf-8"));
    merged.presets_tested.push(...(v.presets_tested || [p]).filter((x) => !merged.presets_tested.includes(x)));
    merged.issues.push(...(v.issues || []));
    merged.screenshots.push(...(v.screenshots || []));
    if (v.notes) merged.notes += `[${p}] ${v.notes} `;
  } catch (e) {
    merged.notes += `parse error for ${p}: ${e.message}; `;
  }
}

const blockers = merged.issues.filter((i) => i.severity === "blocker");
merged.passed = blockers.length === 0;
merged.summary = blockers.length === 0
  ? `axe scan complete; ${merged.issues.length} non-blocker findings across ${merged.presets_tested.length} presets`
  : `${blockers.length} blocker contrast/aria violations across ${merged.presets_tested.length} presets`;

fs.writeFileSync(path.join(OUT_ROOT, "verdict.json"), JSON.stringify(merged, null, 2));
fs.writeFileSync(path.join(OUT_ROOT, "axe.json"), JSON.stringify(merged.issues, null, 2));

console.log(`merged ${merged.presets_tested.length} presets; ${merged.issues.length} issues; passed=${merged.passed}`);
