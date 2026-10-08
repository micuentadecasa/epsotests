const { defineConfig, devices } = require("@playwright/test");
const path = require("path");

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:8765",
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: "python -m epsotests.web_server --host 127.0.0.1 --port 8765",
    cwd: path.resolve(__dirname, ".."),
    url: "http://127.0.0.1:8765/api/health",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
