import { defineConfig } from "@playwright/test";

const PRESETS = ["classic-dark","midnight","studio-light","high-contrast"];

export default defineConfig({
  testDir: ".",
  use: {
    baseURL: "http://localhost:8765",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "..\\.venv\\Scripts\\python -m webui --port 8765",
    cwd: "..",
    url: "http://localhost:8765/api/tracks",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
    ...PRESETS.map((preset) => ({
      name: `review-${preset}`,
      testMatch: /visual-review\.spec\.js$/,
      use: { browserName: "chromium" },
      metadata: { preset },
    })),
  ],
});
