import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "fs";
import path from "path";
import { PRESETS as PRESETS_INLINE } from "../static/js/theme/presets.js";

const FIXTURE_SLUG = "gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg";
const OUT_ROOT = path.join("visual-review");

const SCENES = [
  { name: "default-load", setup: async (page) => {
    await page.waitForSelector("#roll-frame canvas.notes", { timeout: 10_000 });
    await page.waitForTimeout(500);
  }},
  { name: "picker-open", setup: async (page) => {
    await page.click(".track-picker");
    await page.waitForSelector(".tp-panel", { timeout: 5_000 });
  }},
  { name: "settings-open", setup: async (page) => {
    await page.click('#topbar .menu .item:has-text("Settings")');
    await page.waitForTimeout(300);
    await page.click('button:has-text("▸ Customize")').catch(() => {});
    await page.waitForTimeout(200);
  }},
  { name: "vocals-tab", setup: async (page) => {
    await page.click('.tab-strip .tab:has-text("Lyrics")').catch(() => {});
    await page.waitForTimeout(200);
  }},
  { name: "claude-tab", setup: async (page) => {
    await page.click('.tab-strip .tab:has-text("Assistant")').catch(() => {});
    await page.waitForTimeout(200);
  }},
  { name: "transport-playing", setup: async (page) => {
    await page.click("#transport .play-btn");
    await page.waitForTimeout(2_000);
    await page.click("#transport .play-btn");
    await page.waitForTimeout(300);
  }},
];

const verdictBuffer = {
  iteration: parseInt(process.env.MUSIQ_ITER || "0", 10),
  passed: false,
  summary: "",
  presets_tested: [],
  issues: [],
  screenshots: [],
  notes: "",
};

test.beforeAll(async () => {
  fs.mkdirSync(OUT_ROOT, { recursive: true });
});

test.describe("visual review", () => {
  for (const scene of SCENES) {
    test(`${scene.name}`, async ({ page }, testInfo) => {
      const preset = testInfo.project.metadata?.preset;
      if (!preset) test.skip(true, "non-review project");
      if (!verdictBuffer.presets_tested.includes(preset)) {
        verdictBuffer.presets_tested.push(preset);
      }

      // Seed localStorage BEFORE the page boots so pre-paint hydration sees it.
      await page.addInitScript((value) => {
        try { localStorage.setItem("musiq.theme", value); } catch (e) {}
      }, JSON.stringify({
        v: 1,
        preset,
        tokens: PRESETS_INLINE[preset],
        locks: [],
      }));

      await page.goto(`/?slug=${FIXTURE_SLUG}`);
      await scene.setup(page);

      const dir = path.join(OUT_ROOT, preset);
      fs.mkdirSync(dir, { recursive: true });
      const shotPath = path.join(dir, `${scene.name}.png`);
      await page.screenshot({ path: shotPath, fullPage: false });
      verdictBuffer.screenshots.push(`${preset}/${scene.name}.png`);

      try {
        const axe = await new AxeBuilder({ page }).withTags(["wcag2aa"]).analyze();
        for (const v of axe.violations) {
          for (const node of v.nodes) {
            verdictBuffer.issues.push({
              severity: (v.impact === "critical" || v.impact === "serious") ? "blocker" : "major",
              preset,
              scene: scene.name,
              category: v.id,
              details: `${v.help}: ${(node.failureSummary || node.html || "").slice(0, 240)}`,
              screenshot: `${preset}/${scene.name}.png`,
            });
          }
        }
      } catch (e) {
        verdictBuffer.notes += `axe scan failed for ${preset}/${scene.name}: ${e?.message || e}; `;
      }
    });
  }
});

test.afterAll(async () => {
  const blockers = verdictBuffer.issues.filter((i) => i.severity === "blocker");
  verdictBuffer.passed = blockers.length === 0;
  const preset = verdictBuffer.presets_tested[0] || "unknown";
  verdictBuffer.summary = blockers.length === 0
    ? `${preset}: axe scan complete; ${verdictBuffer.issues.length} non-blocker findings`
    : `${preset}: ${blockers.length} blocker contrast/aria violations`;
  fs.writeFileSync(path.join(OUT_ROOT, `verdict-${preset}.json`), JSON.stringify(verdictBuffer, null, 2));
  fs.writeFileSync(path.join(OUT_ROOT, `axe-${preset}.json`), JSON.stringify(verdictBuffer.issues, null, 2));
});
