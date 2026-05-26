import { test, expect } from "@playwright/test";

test.describe("MusIQ-Lab webui", () => {
  test("loads Gorillaz, switches via dropdown, and exercises hotkeys", async ({ page }) => {
    await page.goto("/?slug=gorillaz_silent_running");

    // 1. topbar shows F minor / 107 BPM
    await expect(page.locator(".track-picker .title")).toContainText("Silent Running");
    await expect(page.locator("#topbar .badge.k")).toHaveText("F minor");
    await expect(page.locator("#topbar .badge.t")).toHaveText(/107(\.\d+)? BPM/);

    // 2. open the dropdown
    await page.click(".track-picker");
    await expect(page.locator(".tp-panel")).toBeVisible();

    // 3. close it (Escape)
    await page.keyboard.press("Escape");
    await expect(page.locator(".tp-panel")).toHaveCount(0);

    // 4. canvas exists and has been sized
    const canvas = page.locator("#roll-frame canvas.notes");
    await expect(canvas).toBeVisible();
    const dims = await canvas.evaluate((el) => ({ w: el.width, h: el.height }));
    expect(dims.w).toBeGreaterThan(100);

    // 5. click bass row in sidebar — highlightedStem should change
    await page.click('.track-row[data-stem="bass"]');
    await expect(page.locator('.track-row[data-stem="bass"]')).toHaveClass(/highlighted/);

    // 6. press Space — playback starts (engine state is internal but we can observe playButton)
    await page.locator("#viewer-main").click();    // satisfy autoplay policy
    await page.keyboard.press("Space");
    await page.waitForTimeout(500);
    await expect(page.locator("#transport .play-btn")).toHaveText("⏸");

    // 7. press Space — pauses
    await page.keyboard.press("Space");
    await expect(page.locator("#transport .play-btn")).toHaveText("▶");

    // 8. ? opens the shortcuts modal
    await page.keyboard.press("Shift+/");
    await expect(page.locator("text=Keyboard shortcuts").first()).toBeVisible();
    await page.keyboard.press("Escape");
  });
});
