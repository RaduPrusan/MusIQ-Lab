import { test, expect } from "@playwright/test";

test.describe("rename track", () => {
  // Restore a known label BEFORE each test so order doesn't matter.
  // We use charlie_puth_attention (slug-named file → identify_track returns
  // ('', slug) → ideal target for testing the rename feature).
  test.beforeEach(async ({ request }) => {
    await request.patch("/api/tracks/charlie_puth_attention", {
      data: { display_name: "Charlie Puth - Attention" },
    }).catch(() => {});
  });

  // Restore the canonical label after the suite (don't leave test labels in cache).
  test.afterAll(async ({ request }) => {
    await request.patch("/api/tracks/charlie_puth_attention", {
      data: { display_name: "Charlie Puth - Attention" },
    }).catch(() => {});
  });

  test("pencil → modal → save updates topbar, document.title, and lyrics tab", async ({ page }) => {
    await page.goto("/?slug=charlie_puth_attention");
    await expect(page.locator(".track-picker .title")).toBeVisible();

    // Open the rename modal via the pencil button
    await page.getByTitle("Rename track").click();
    const input = page.locator(".rename-modal-input");
    await expect(input).toBeFocused();

    // Type a new artist - title and Save (Enter)
    await input.fill("Test Artist - Test Title");
    await page.keyboard.press("Enter");

    // Modal closes, topbar reflects the new name
    await expect(page.locator(".rename-modal-overlay")).toHaveCount(0);
    await expect(page.locator(".track-picker .title")).toHaveText("Test Artist - Test Title");

    // Browser tab title updated
    await expect(page).toHaveTitle("Test Artist - Test Title — MusIQ-Lab");

    // Open Lyrics tab and verify the header reflects the smart split.
    // Tabs are `<button class="tab" data-tab="lyrics">Lyrics</button>`, not role=tab.
    await page.locator('button.tab[data-tab="lyrics"]').click();
    await expect(page.locator(".lyrics-artist")).toContainText("Test Artist");
    await expect(page.locator(".lyrics-title")).toContainText("Test Title");
  });

  test("Esc closes the modal without saving", async ({ page }) => {
    await page.goto("/?slug=charlie_puth_attention");
    const titleBefore = await page.locator(".track-picker .title").textContent();

    await page.getByTitle("Rename track").click();
    await page.locator(".rename-modal-input").fill("Should Not Be Saved");
    await page.keyboard.press("Escape");

    await expect(page.locator(".rename-modal-overlay")).toHaveCount(0);
    await expect(page.locator(".track-picker .title")).toHaveText(titleBefore.trim());
  });

  test("validation error stays in the modal", async ({ page }) => {
    await page.goto("/?slug=charlie_puth_attention");
    await page.getByTitle("Rename track").click();
    // Path char rejected by server
    await page.locator(".rename-modal-input").fill("foo/bar");
    await page.keyboard.press("Enter");
    // Modal stays open with error banner
    await expect(page.locator(".rename-modal-error")).toBeVisible();
    await expect(page.locator(".rename-modal-error")).toContainText("invalid character");
    await expect(page.locator(".rename-modal-overlay")).toBeVisible();
  });
});
