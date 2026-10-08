const { test, expect } = require("@playwright/test");

function expectNoApiRequests(page) {
  const requests = [];
  page.on("request", (request) => {
    if (request.url().includes("/api/")) requests.push(request.url());
  });
  return requests;
}

async function waitForQuestion(page) {
  await expect(page.locator("#question-prompt")).not.toHaveText("");
  await expect(page.locator("#answer-options input[type=radio]")).toHaveCount(4);
}

async function enableSolution(page) {
  await page.locator("#answer-options input[type=radio]").first().check();
  await page.locator("#explain-button").click();
  await expect(page.locator("#solution")).toBeVisible();
  await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "true");
}

test.describe("GitHub Pages static catalog", () => {
  test.beforeEach(({ }, testInfo) => {
    testInfo.skip(!process.env.EPSOTESTS_STATIC, "run with EPSOTESTS_STATIC=1");
  });

  test("visual question advances and keeps solution review enabled", async ({ page }, testInfo) => {
    const apiRequests = expectNoApiRequests(page);
    await page.goto("./");
    await waitForQuestion(page);
    const before = await page.locator("#item-meta").textContent();
    await expect(page.locator("#stimulus svg").first()).toBeVisible();
    await enableSolution(page);

    await page.locator("#next-button").click();
    await expect(page.locator("#item-meta")).not.toHaveText(before);
    await expect(page.locator("#item-meta")).toContainText("seed 43");
    await expect(page.locator("#solution")).toBeVisible();
    await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#solution")).toContainText("Solution");
    await page.screenshot({ path: testInfo.outputPath("visual-next-question.png"), fullPage: true });
    await page.locator("#hide-button").click();
    await expect(page.locator("#solution")).toBeHidden();
    await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "false");
    expect(apiRequests).toEqual([]);
  });

  test("numerical chart question advances without an API", async ({ page }) => {
    const apiRequests = expectNoApiRequests(page);
    await page.goto("./");
    await page.locator("#family").selectOption("numerical");
    await page.locator("#variant").selectOption("growth");
    await page.locator("#representation").selectOption("bar-chart");
    await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
    await waitForQuestion(page);
    const before = await page.locator("#item-meta").textContent();
    await expect(page.locator('#stimulus svg[data-chart-type="bar-chart"]')).toBeVisible();
    await enableSolution(page);

    await page.locator("#next-button").click();
    await expect(page.locator("#item-meta")).not.toHaveText(before);
    await expect(page.locator("#solution")).toBeVisible();
    await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "true");
    expect(apiRequests).toEqual([]);
  });

  test("verbal passage advances without an API and keeps evidence review", async ({ page }) => {
    const apiRequests = expectNoApiRequests(page);
    await page.goto("./");
    await page.locator("#family").selectOption("verbal");
    await page.locator("#variant").selectOption("inference");
    await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
    await waitForQuestion(page);
    const before = await page.locator("#item-meta").textContent();
    await expect(page.locator(".passage-text p")).toHaveCount(3);
    await enableSolution(page);
    await expect(page.locator("#solution")).toContainText(/Evidence from the passage|paragraph/);

    await page.locator("#next-button").click();
    await expect(page.locator("#item-meta")).not.toHaveText(before);
    await expect(page.locator("#solution")).toBeVisible();
    await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "true");
    expect(apiRequests).toEqual([]);
  });
});
