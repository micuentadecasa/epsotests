const { test, expect } = require("@playwright/test");

async function waitForQuestion(page) {
  await expect(page.locator("#question-prompt")).not.toHaveText("");
  await expect(page.locator("#answer-options input[type=radio]")).toHaveCount(4);
  await expect(page.locator("#controls-form button[type=submit]")).toBeEnabled();
}

async function questionState(page) {
  return page.evaluate(() => {
    const prompt = document.querySelector("#question-prompt").getBoundingClientRect();
    return {
      identity: document.querySelector("#item-meta").textContent,
      questionId: document.querySelector("#item-meta").dataset.questionId,
      methodSignature: document.querySelector("#item-meta").dataset.methodSignature,
      answerSignature: document.querySelector("#item-meta").dataset.answerSignature,
      calculationSignature: document.querySelector("#item-meta").dataset.calculationSignature,
      evidenceSignature: document.querySelector("#item-meta").dataset.evidenceSignature,
      explanationSignature: document.querySelector("#item-meta").dataset.explanationSignature,
      seed: document.querySelector("#seed").value,
      stimulus: document.querySelector("#stimulus").innerHTML,
      family: document.querySelector("#family").value,
      variant: document.querySelector("#variant").value,
      representation: document.querySelector("#representation").value,
      difficulty: document.querySelector("#difficulty").value,
      profile: document.querySelector("#profile").value,
      viewport: { width: window.innerWidth, height: window.innerHeight },
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
    expect(after.evidenceSignature).not.toBe(before.evidenceSignature);
    expect(after.explanationSignature).not.toBe(before.explanationSignature);
    expect(after.promptVisible).toBe(true);
    await expect(page.locator("#family")).toHaveValue("verbal");
    await expect(page.locator("#variant")).toHaveValue("inference");
    await expect(page.locator("#difficulty")).toHaveValue("medium");
    await expect(page.locator("#profile")).toHaveValue("standard");
    await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "true");
  });

  test("repeated Generate advances the selected family before cycling", async ({ page }) => {
    await page.goto("./");
    await waitForQuestion(page);
    const states = [await questionState(page)];

    for (let index = 0; index < 3; index += 1) {
      await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
      const previous = states.at(-1);
      await expect.poll(async () => (await questionState(page)).questionId).not.toBe(previous.questionId);
      const current = await questionState(page);
      expect(current.questionId).not.toBe(previous.questionId);
      expect(current.stimulus).not.toBe(previous.stimulus);
      states.push(current);
    }

    expect(states.map(({ seed }) => seed)).toEqual(["42", "43", "42", "43"]);
    expect(new Set(states.slice(1).map(({ questionId }) => questionId)).size).toBe(2);
  });

  test("Generate advances one sequence across visual and numerical family switches", async ({ page }) => {
    const apiSeeds = [];
    page.on("request", (request) => {
      if (request.url().includes("/api/question?")) {
        apiSeeds.push(new URL(request.url()).searchParams.get("seed"));
      }
    });
    await page.goto("./");
    await page.locator("#profile").selectOption("five-option");
    await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
    await expect(page.locator("#answer-options input[type=radio]")).toHaveCount(5);
    await enableSolution(page);

    const states = [await questionState(page)];
    const generate = async (selectedFamily) => {
      await page.locator("#family").selectOption(selectedFamily);
      if (selectedFamily === "numerical") {
        await page.locator("#variant").selectOption("growth");
        await page.locator("#representation").selectOption("bar-chart");
      } else {
        await page.locator("#variant").selectOption("sequence");
      }
      const previous = states.at(-1);
      await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
      await expect.poll(async () => (await questionState(page)).questionId).not.toBe(previous.questionId);
      await expect(page.locator("#solution")).toBeVisible();
      await expect(page.locator("#explain-button")).toHaveAttribute("aria-pressed", "true");
      const current = await questionState(page);
      expect(current.questionId).not.toBe(previous.questionId);
      expect(current.stimulus).not.toBe(previous.stimulus);
      await expect.poll(async () => (await questionState(page)).promptVisible).toBe(true);
      expect(current.promptVisible).toBe(true);
      expect(current.viewport).toEqual(previous.viewport);
      expect(current.difficulty).toBe("medium");
      expect(current.profile).toBe("five-option");
      states.push(current);
    };

    await generate("numerical");
    await generate("visual");
    await generate("numerical");

    expect(new Set(states.map(({ questionId }) => questionId)).size).toBe(4);
    expect(states.map(({ seed }) => seed)).toEqual(["42", "42", "43", "43"]);
    expect(states.map(({ family, variant, representation }) => [family, variant, representation])).toEqual([
      ["visual", "sequence", "table"],
      ["numerical", "growth", "bar-chart"],
      ["visual", "sequence", "bar-chart"],
      ["numerical", "growth", "bar-chart"],
    ]);
    if (process.env.EPSOTESTS_STATIC === "1") {
      expect(apiSeeds).toEqual([]);
    } else {
      expect(apiSeeds.slice(-4)).toEqual(["42", "42", "43", "43"]);
    }
  });

  test("Generate changes the numerical method and answer before cycling", async ({ page }) => {
    await page.goto("./");
    await page.locator("#family").selectOption("numerical");
    await page.locator("#variant").selectOption("ratio");
    await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
    await waitForQuestion(page);
    const first = await questionState(page);
    await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
    await expect.poll(async () => (await questionState(page)).questionId).not.toBe(first.questionId);
    const second = await questionState(page);
    expect(second.methodSignature).not.toBe(first.methodSignature);
    expect(second.answerSignature).not.toBe(first.answerSignature);
    expect(second.calculationSignature).not.toBe(first.calculationSignature);
    expect(second.explanationSignature).not.toBe(first.explanationSignature);

    await page.locator("#controls-form").getByRole("button", { name: /Generate question/ }).click();
    await expect.poll(async () => (await questionState(page)).questionId).not.toBe(second.questionId);
    const third = await questionState(page);
    expect(third.methodSignature).toBe(first.methodSignature);
    expect(third.answerSignature).toBe(first.answerSignature);
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
