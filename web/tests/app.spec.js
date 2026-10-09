const { test, expect } = require("@playwright/test");

async function waitForQuestion(page) {
  await expect(page.locator("#question-prompt")).not.toHaveText("");
  await expect(page.locator("#answer-options input[type=radio]")).toHaveCount(4);
}

async function questionState(page) {
  return page.evaluate(() => {
    const prompt = document.querySelector("#question-prompt").getBoundingClientRect();
    return {
      identity: document.querySelector("#item-meta").textContent,
      seed: document.querySelector("#seed").value,
      stimulus: document.querySelector("#stimulus").innerHTML,
      scrollY: window.scrollY,
      promptVisible: prompt.top >= 0 && prompt.bottom <= window.innerHeight,
    };
  });
}

async function enableSolution(page) {
  await page.locator("#answer-options input[type=radio]").first().check();
  await page.locator("#explain-button").click();
  await expect(page.locator("#solution")).toBeVisible();
  await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "true");
}

test.describe("learner question flows", () => {
  test("visual abstract renders figures and persists solution review across Next Question", async ({ page }) => {
    await page.goto("./");
    await waitForQuestion(page);
    await expect(page.locator("#stimulus svg").first()).toBeVisible();

    await page.locator("#profile").selectOption("five-option");
    await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
    await expect(page.locator("#answer-options input[type=radio]")).toHaveCount(5);
    await enableSolution(page);
    await page.waitForTimeout(500);
    const before = await questionState(page);

    await page.locator("#next-button").click();
    await expect(page.locator("#question-prompt")).not.toHaveText("");
    await expect(page.locator("#solution")).toBeVisible();
    await page.waitForTimeout(800);
    const after = await questionState(page);
    expect(after.identity).not.toBe(before.identity);
    expect(after.seed).toBe("43");
    expect(after.stimulus).not.toBe(before.stimulus);
    expect(after.promptVisible).toBe(true);
    await expect(page.locator("#family")).toHaveValue("visual");
    await expect(page.locator("#variant")).toHaveValue("sequence");
    await expect(page.locator("#difficulty")).toHaveValue("medium");
    await expect(page.locator("#profile")).toHaveValue("five-option");
    await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#explain-button")).toHaveAccessibleName(/Hide solution/i);

    await page.locator("#hide-button").click();
    await expect(page.locator("#solution")).toBeHidden();
    await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "false");
  });

  test("numerical chart question shows calculations after answer submission and persists on Next Question", async ({ page }) => {
    await page.goto("./");
    await page.locator("#family").selectOption("numerical");
    await page.locator("#variant").selectOption("growth");
    await page.locator("#representation").selectOption("bar-chart");
    await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
    await waitForQuestion(page);
    await expect(page.locator('#stimulus svg[data-chart-type="bar-chart"]')).toBeVisible();
    await enableSolution(page);
    await expect(page.locator("#solution")).toContainText(/Step-by-step|Calculation method/);
    await page.waitForTimeout(500);
    const before = await questionState(page);

    await page.locator("#next-button").click();
    await expect(page.locator("#solution")).toBeVisible();
    await page.waitForTimeout(800);
    const after = await questionState(page);
    expect(after.identity).not.toBe(before.identity);
    expect(after.seed).toBe("43");
    expect(after.stimulus).not.toBe(before.stimulus);
    expect(after.promptVisible).toBe(true);
    await expect(page.locator("#family")).toHaveValue("numerical");
    await expect(page.locator("#variant")).toHaveValue("growth");
    await expect(page.locator("#representation")).toHaveValue("bar-chart");
    await expect(page.locator("#difficulty")).toHaveValue("medium");
    await expect(page.locator("#profile")).toHaveValue("standard");
    await expect(page.locator("#solution")).toContainText(/Solution preference is enabled|correct answer/i);
  });

  test("verbal passage uses accessible radio controls and evidence review persists on Next Question", async ({ page }) => {
    await page.goto("./");
    await page.locator("#family").selectOption("verbal");
    await page.locator("#variant").selectOption("inference");
    await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
    await waitForQuestion(page);
    await expect(page.locator(".passage-text p")).toHaveCount(3);
    await expect(page.getByRole("radio")).toHaveCount(4);
    await enableSolution(page);
    await expect(page.locator("#solution")).toContainText(/Evidence from the passage|paragraph/);
    await page.waitForTimeout(500);
    const before = await questionState(page);

    await page.locator("#next-button").click();
    await expect(page.locator("#solution")).toBeVisible();
    await page.waitForTimeout(800);
    const after = await questionState(page);
    expect(after.identity).not.toBe(before.identity);
    expect(after.seed).toBe("43");
    expect(after.stimulus).not.toBe(before.stimulus);
    expect(after.promptVisible).toBe(true);
    await expect(page.locator("#family")).toHaveValue("verbal");
    await expect(page.locator("#variant")).toHaveValue("inference");
    await expect(page.locator("#difficulty")).toHaveValue("medium");
    await expect(page.locator("#profile")).toHaveValue("standard");
    await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "true");
  });

  test("solution toggle is keyboard accessible and session-persistent", async ({ page }) => {
    await page.goto("./");
    await waitForQuestion(page);
    const firstAnswer = page.getByRole("radio").first();
    await firstAnswer.focus();
    await page.keyboard.press("Space");
    await expect(firstAnswer).toBeChecked();
    const toggle = page.locator("#explain-button");
    await toggle.focus();
    await page.keyboard.press("Enter");
    await expect(toggle).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#solution")).toBeVisible();
    await expect(page.evaluate(() => sessionStorage.getItem("epsotests:show-solution"))).resolves.toBe("true");
  });
});
