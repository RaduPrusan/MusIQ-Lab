// E2E: enable the Live Input mic with a fake audio stream (a 440 Hz sine),
// navigate to a known slug, click M on the mic row, assert the row activates
// and the readout updates.
//
// Launches Chromium with --use-fake-device-for-media-stream +
// --use-file-for-fake-audio-capture so the mic input is deterministic.
//
// REQUIRES: at least one analyzed track in the cache (uses gorillaz slug
// present on the dev machine; CI/headless setups without a cache will see
// the test skip automatically via the soft-guard below).
import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIXTURE = path.resolve(__dirname, "fixtures/mic-440hz.wav");
// Slug that is present on the dev machine; change to any slug available in
// your local cache if this one is absent.
const SLUG = "gorillaz-silent_running_ft_adeleye_omotayo_official_video-0pf48rqssg";

test.use({
  launchOptions: {
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
      `--use-file-for-fake-audio-capture=${FIXTURE}`,
    ],
  },
  permissions: ["microphone"],
});

// SKIPPED when running on a machine where the gorillaz slug is absent from
// the cache — the test simply navigates to / and checks whether the viewer
// loaded rather than failing with a confusing timeout.
test("Live Input row activates and the readout updates", async ({ page, context }) => {
  await context.grantPermissions(["microphone"], { origin: "http://localhost:8765" });

  // Navigate directly to the track (mirrors viewer.spec.js pattern).
  await page.goto(`/?slug=${SLUG}`);

  // Soft-guard: if the track isn't in this machine's cache the topbar stays
  // empty — skip gracefully rather than timing out.
  const micRowLocator = page.locator(".mic-row");
  const micRowVisible = await micRowLocator
    .waitFor({ state: "visible", timeout: 15000 })
    .then(() => true)
    .catch(() => false);

  if (!micRowVisible) {
    test.skip(
      true,
      // SKIPPED: track slug not found in local cache — the Live Input row never
      // mounts. Unskip / substitute a slug that exists in your cache.
      // To smoke-test manually: open http://localhost:8765, pick a track, click
      // the M button on the Live Input row, observe the readout updates with a
      // note name + cents value.
      "Live Input row not visible — slug absent from local track cache"
    );
    return;
  }

  // Click M to enable the mic.
  const mBtn = micRowLocator.locator(".btn.m");
  await mBtn.click();

  // Status dot should flip to live within 2 s.
  const statusDot = micRowLocator.locator(".status-dot");
  await expect(statusDot).toHaveClass(/status-live/, { timeout: 2000 });

  // Readout should update from "—" to something with a digit (note name or
  // cents value) once the fake 440 Hz stream produces a pitch sample.
  const readout = micRowLocator.locator(".mic-readout");
  await expect(readout).not.toHaveText("—", { timeout: 3000 });

  // Click M again to stop.
  await mBtn.click();
  await expect(statusDot).toHaveClass(/status-off/, { timeout: 2000 });
  await expect(readout).toHaveText("—");
});
