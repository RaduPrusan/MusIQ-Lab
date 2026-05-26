import { test, expect } from "@playwright/test";

test.describe("Analyze YouTube URL", () => {
  test("opens modal and hits dry_run endpoint with the URL", async ({ page }) => {
    await page.goto("/");
    let dryRunBody = null;
    await page.route("**/api/tools/analyze/youtube", async (route) => {
      const post = await route.request().postDataJSON();
      if (post.dry_run) {
        dryRunBody = post;
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            predicted_slug: "fake_song-vidid12345",
            exists: false,
            suggested_new_slug: "fake_song-vidid12345-2",
          }),
        });
      } else {
        // Don't actually run analyze — return a minimal NDJSON stream that ends.
        await route.fulfill({
          status: 200,
          contentType: "application/x-ndjson",
          body: '{"type":"error","message":"test stub","kind":"internal"}\n',
        });
      }
    });
    await page.locator(".track-picker").click();
    await page.getByRole("button", { name: "+ YT" }).click();
    // Scope to the modal panel: the heading is unique once the modal opens,
    // and panel is its direct parent (see showAnalyzeModal in analyze-modal.js).
    // This is more refactor-resistant than inline-style attribute matching.
    const heading = page.getByRole("heading", { name: /Analyze YouTube URL/i });
    await expect(heading).toBeVisible();
    const modal = heading.locator("..");
    await modal.locator('input[type="text"]').fill("https://www.youtube.com/watch?v=AbCdEf12345");
    await modal.getByRole("button", { name: "Analyze" }).click();
    // The streaming step should now be rendered with the test-stub error.
    await expect(page.locator("text=test stub")).toBeVisible({ timeout: 5000 });
    expect(dryRunBody).toMatchObject({ url: "https://www.youtube.com/watch?v=AbCdEf12345", dry_run: true });
  });
});
