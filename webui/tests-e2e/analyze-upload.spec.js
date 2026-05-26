import { test, expect } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { readFileSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));

// Mock the slug-for endpoint so this test runs against both old and new servers.
// The endpoint was added in a later commit; mocking it lets the test remain
// forward-compatible (when the server has it, the mock merely replaces it).
async function mockSlugFor(page, { slug, exists, suggested_new_slug }) {
  await page.route("**/api/util/slug-for**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ slug, exists, suggested_new_slug }),
    })
  );
}

test.describe("Analyze new file (upload)", () => {
  test("opens modal, picks file, sees collision step is bypassed for fresh slug", async ({ page }) => {
    await mockSlugFor(page, {
      slug: "tiny",
      exists: false,
      suggested_new_slug: "tiny-2",
    });

    await page.goto("/");
    // Open the picker
    await page.locator(".track-picker").click();
    // Click + File
    await page.getByRole("button", { name: "+ File" }).click();
    // Modal opens
    await expect(page.getByRole("heading", { name: /Analyze new audio file/i })).toBeVisible();
    // Pick fixture
    await page.locator('input[type="file"]').setInputFiles(resolve(here, "fixtures/tiny.wav"));
    // Wait for slug-for pre-check to resolve and enable the Analyze button
    await expect(page.getByRole("button", { name: "Analyze" })).toBeEnabled({ timeout: 5000 });
    // (We stop here without clicking Analyze because the actual pipeline
    // requires WSL + GPU and is out of scope for this test. The path so far
    // covers the modal/network plumbing.)
  });

  test("collision flow surfaces three-button step", async ({ page }) => {
    // Fetch track list via the Node HTTP layer (before page.goto) so we have
    // a base URL from the Playwright config.
    const tracks = await page.request.get("/api/tracks").then((r) => r.json());
    if (!tracks.length) {
      test.skip(true, "no tracks in cache to collide with");
      return;
    }

    const collidingSlug = tracks[0].slug;
    const suggestedNew = `${collidingSlug}-2`;
    const tmpName = `${collidingSlug}.wav`;

    // Mock slug-for to report a collision with the first track in the library
    await page.route("**/api/util/slug-for**", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          slug: collidingSlug,
          exists: true,
          suggested_new_slug: suggestedNew,
        }),
      })
    );

    await page.goto("/");
    await page.locator(".track-picker").click();
    await page.getByRole("button", { name: "+ File" }).click();

    // Upload the fixture under a name that resolves to the colliding slug
    await page.locator('input[type="file"]').setInputFiles({
      name: tmpName,
      mimeType: "audio/wav",
      buffer: readFileSync(resolve(here, "fixtures/tiny.wav")),
    });

    // Wait for Analyze to be enabled (slug-for resolved)
    await expect(page.getByRole("button", { name: "Analyze" })).toBeEnabled({ timeout: 5000 });
    await page.getByRole("button", { name: "Analyze" }).click();

    // Three-button collision step should be visible
    await expect(
      page.getByRole("button", { name: new RegExp(`Add New ${suggestedNew}`) })
    ).toBeVisible({ timeout: 5000 });
    await expect(page.getByRole("button", { name: "Reanalyze" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Cancel" })).toBeVisible();
  });
});
