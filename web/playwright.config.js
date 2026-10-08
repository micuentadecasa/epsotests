const { defineConfig, devices } = require("@playwright/test");
const path = require("path");

const staticMode = process.env.EPSOTESTS_STATIC === "1";
const staticRoot = path.resolve(__dirname, "..", ".playwright-static-root");
const port = staticMode ? 8766 : 8765;

module.exports = defineConfig({
  testDir: "./tests",
  timeout: 30_000,
  fullyParallel: true,
  reporter: "list",
  use: {
    baseURL: `http://127.0.0.1:${port}${staticMode ? "/epsotests/" : ""}`,
    trace: "retain-on-failure",
    ...devices["Desktop Chrome"],
  },
  webServer: staticMode
    ? {
        command: `rm -rf "${staticRoot}" && python scripts/build_pages.py --output "${staticRoot}/epsotests" && python -m http.server ${port} --directory "${staticRoot}"`,
        cwd: path.resolve(__dirname, ".."),
        url: `http://127.0.0.1:${port}/epsotests/`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      }
    : {
        command: "python -m epsotests.web_server --host 127.0.0.1 --port 8765",
        cwd: path.resolve(__dirname, ".."),
        url: "http://127.0.0.1:8765/api/health",
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
      },
});
