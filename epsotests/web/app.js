const VISUAL_FORMATS = [
  ["sequence", "Sequence"],
  ["matrix-2x2", "Matrix · 2 × 2"],
  ["matrix-3x3", "Matrix · 3 × 3"],
  ["analogy", "Transformation analogy"],
];
const NUMERICAL_OPERATIONS = [
  ["percentage-change", "Percentage change"],
  ["ratio", "Ratio"],
  ["proportion", "Proportion"],
  ["total", "Total"],
  ["growth", "Growth"],
  ["comparison", "Comparison"],
  ["multi-step", "Multi-step calculation"],
];
const VERBAL_TYPES = [
  ["reading-comprehension", "Reading comprehension"],
  ["inference", "Inference"],
  ["true-false", "True / false"],
];

const state = {
  question: null,
  solutionToken: null,
  solution: null,
  solutionPreference: sessionStorage.getItem("epsotests:show-solution") === "true",
  loading: false,
};

const $ = (selector) => document.querySelector(selector);
const controlsForm = $("#controls-form");
const answerForm = $("#answer-form");
const family = $("#family");
const variant = $("#variant");
const variantLabel = $("#variant-label");
const representationField = $("#representation-field");
const representation = $("#representation");
const difficulty = $("#difficulty");
const profile = $("#profile");
const seed = $("#seed");
const status = $("#status");
const stimulus = $("#stimulus");
const answerOptions = $("#answer-options");
const explainButton = $("#explain-button");
const hideButton = $("#hide-button");
const nextButton = $("#next-button");
const solutionPanel = $("#solution");
const solutionContent = $("#solution-content");
const solutionResult = $("#solution-result");
const answerFeedback = $("#answer-feedback");

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setStatus(message, isError = false) {
  status.textContent = message;
  status.classList.toggle("error", isError);
}

function updateVariantOptions() {
  const selectedFamily = family.value;
  const options = selectedFamily === "visual"
    ? VISUAL_FORMATS
    : selectedFamily === "numerical"
      ? NUMERICAL_OPERATIONS
      : VERBAL_TYPES;
  variantLabel.textContent = selectedFamily === "visual" ? "Question format" : selectedFamily === "numerical" ? "Operation" : "Question type";
  variant.replaceChildren(...options.map(([value, label]) => {
    const option = element("option", null, label);
    option.value = value;
    return option;
  }));
  representationField.hidden = selectedFamily !== "numerical";
}

function safeSvg(svgText, label = "Figure") {
  if (typeof svgText !== "string" || !svgText.trim()) return null;
  const parsed = new DOMParser().parseFromString(svgText, "image/svg+xml");
  const root = parsed.documentElement;
  if (!root || root.nodeName.toLowerCase() !== "svg" || parsed.querySelector("parsererror")) return null;
  root.querySelectorAll("script, foreignObject").forEach((node) => node.remove());
  root.querySelectorAll("*").forEach((node) => {
    [...node.attributes].forEach((attribute) => {
      if (/^on/i.test(attribute.name) || /javascript:/i.test(attribute.value)) node.removeAttribute(attribute.name);
    });
  });
  root.setAttribute("role", "img");
  if (!root.getAttribute("aria-label")) root.setAttribute("aria-label", label);
  return document.importNode(root, true);
}

function appendFigure(parent, figure, label) {
  const card = element("figure", "figure-card");
  const svg = safeSvg(figure?.svg, label);
  if (svg) card.append(svg);
  const caption = element("figcaption", null, label);
  card.append(caption);
  parent.append(card);
}

function renderVisualStimulus(data) {
  const type = data.type;
  if (type === "sequence") {
    const grid = element("div", "figure-grid");
    data.frames.forEach((frame, index) => appendFigure(grid, frame, `Frame ${index + 1}`));
    const missing = element("figure", "figure-card");
    missing.append(element("div", "missing-figure", "?"), element("figcaption", null, "Next"));
    grid.append(missing);
    stimulus.append(grid);
    return;
  }
  if (type === "matrix") {
    const grid = element("div", "matrix-grid");
    grid.dataset.size = String(data.rows);
    data.grid.flat().forEach((figure, index) => {
      if (figure) appendFigure(grid, figure, `Cell ${index + 1}`);
      else {
        const missing = element("div", "missing-figure", "?");
        missing.setAttribute("aria-label", "Missing matrix cell");
        grid.append(missing);
      }
    });
    stimulus.append(grid);
    return;
  }
  if (type === "analogy") {
    const grid = element("div", "analogy-grid");
    appendFigure(grid, data.left.A, "A");
    grid.append(element("div", "relation", ":"));
    appendFigure(grid, data.left.B, "B");
    grid.append(element("div", "relation", "∷"));
    appendFigure(grid, data.right.C, "C");
    grid.append(element("div", "relation", ":"));
    const missing = element("div", "figure-card");
    missing.append(element("div", "missing-figure", "?"), element("figcaption", null, "Answer"));
    grid.append(missing);
    stimulus.append(grid);
    return;
  }
  stimulus.append(element("p", null, "This stimulus format is not available."));
}

function sanitizedTable(tableHtml) {
  const parsed = new DOMParser().parseFromString(tableHtml, "text/html");
  parsed.querySelectorAll("script, iframe, object, embed, form").forEach((node) => node.remove());
  parsed.querySelectorAll("*").forEach((node) => {
    [...node.attributes].forEach((attribute) => {
      if (/^on/i.test(attribute.name) || /javascript:/i.test(attribute.value)) node.removeAttribute(attribute.name);
    });
  });
  return parsed.querySelector("table");
}

function renderNumericalStimulus(data) {
  const heading = element("h3", "passage-title", data.title || "Source data");
  stimulus.append(heading);
  if (data.type === "table" && data.html) {
    const table = sanitizedTable(data.html);
    if (table) {
      const wrapper = element("div", "table-wrap");
      wrapper.append(document.importNode(table, true));
      stimulus.append(wrapper);
    }
  } else {
    const svg = safeSvg(data.svg, data.title || "Numerical chart");
    if (svg) stimulus.append(svg);
  }
  if (data.accessibleText) stimulus.append(element("p", "accessible-note", data.accessibleText));
}

function renderPassageStimulus(data) {
  const passage = data.passage || {};
  stimulus.append(element("h3", "passage-title", passage.title || data.title || "Passage"));
  const text = element("div", "passage-text");
  (passage.paragraphs || String(data.text || "").split("\n\n")).forEach((paragraph) => text.append(element("p", null, paragraph)));
  stimulus.append(text);
}

function renderStimulus(question) {
  stimulus.replaceChildren();
  const data = question.stimulus || {};
  if (question.exam === "abstract") renderVisualStimulus(data);
  else if (question.exam === "numerical") renderNumericalStimulus(data);
  else renderPassageStimulus(data);
}

function renderOptions(question) {
  answerOptions.replaceChildren();
  answerOptions.append(element("legend", null, "Select one answer"));
  question.options.forEach((option) => {
    const label = element("label", "answer-option");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "answer";
    input.value = option.id;
    input.setAttribute("aria-label", `Option ${option.id}`);
    const letter = element("span", "answer-letter", option.id);
    const text = element("span", "option-text", option.label || option.text || String(option.value));
    label.append(input, letter, text);
    if (option.svg) {
      const figure = element("span", "option-figure");
      const svg = safeSvg(option.svg, `Answer option ${option.id}`);
      if (svg) figure.append(svg);
      label.append(figure);
    }
    input.addEventListener("change", () => {
      explainButton.disabled = false;
      if (state.solutionPreference) revealSolution(option.id);
    });
    answerOptions.append(label);
  });
  explainButton.disabled = !question.options.length;
}

function renderQuestion(question, token) {
  state.question = question;
  state.solutionToken = token;
  state.solution = null;
  $("#item-meta").textContent = `${question.exam} reasoning · item ${question.itemNumber || 1} · seed ${question.metadata?.seed ?? seed.value}`;
  $("#question-heading").textContent = question.format || question.questionType || "Question";
  $("#question-prompt").textContent = question.question;
  $("#difficulty-badge").textContent = question.difficulty;
  answerFeedback.textContent = "";
  answerFeedback.className = "answer-feedback";
  solutionPanel.hidden = true;
  solutionContent.replaceChildren();
  solutionResult.textContent = "";
  explainButton.hidden = false;
  hideButton.hidden = true;
  updateToggleLabel();
  renderStimulus(question);
  renderOptions(question);
  if (state.solutionPreference) revealSolution();
}

function selectedOption() {
  return answerForm.querySelector("input[name=answer]:checked")?.value || "";
}

async function fetchQuestion() {
  if (state.loading) return;
  state.loading = true;
  setStatus("Generating a deterministic question…");
  const params = new URLSearchParams({
    family: family.value,
    difficulty: difficulty.value,
    profile: profile.value,
    seed: seed.value,
  });
  if (family.value === "visual") params.set("format", variant.value);
  if (family.value === "numerical") {
    params.set("operation", variant.value);
    params.set("representation", representation.value);
  }
  if (family.value === "verbal") params.set("questionType", variant.value);
  try {
    const response = await fetch(`/api/question?${params.toString()}`, { headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Question generation failed");
    renderQuestion(payload.question, payload.solutionToken);
    setStatus(`${payload.question.optionCount}-option question ready. Select an answer, then review the logic when you are ready.`);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.loading = false;
  }
}

function updateToggleLabel() {
  const active = state.solutionPreference;
  explainButton.setAttribute("aria-pressed", String(active));
  explainButton.setAttribute("aria-label", active ? "Hide solution and disable automatic solution review" : "Explain Logic / Ver solución and enable automatic solution review");
  explainButton.innerHTML = active
    ? "Hide Solution <span aria-hidden=\"true\">/</span> Ocultar solución"
    : "Explain Logic <span aria-hidden=\"true\">/</span> Ver solución";
  explainButton.classList.toggle("toggle-active", active);
  hideButton.hidden = !active || !state.solution;
}

function setSolutionPreference(enabled) {
  state.solutionPreference = enabled;
  sessionStorage.setItem("epsotests:show-solution", String(enabled));
  updateToggleLabel();
}

function renderSolution(result) {
  state.solution = result;
  solutionPanel.hidden = false;
  solutionContent.replaceChildren();
  solutionResult.textContent = result.isCorrect === null ? "Solution shown" : result.isCorrect ? "Correct" : "Review this answer";
  solutionResult.className = `result-badge ${result.isCorrect === null ? "" : result.isCorrect ? "correct" : "incorrect"}`;

  if (result.selectedReason) solutionContent.append(element("p", "solution-copy", result.selectedReason));
  if (result.explanation) solutionContent.append(element("p", "solution-copy", result.explanation));
  if (result.ruleText) appendSolutionBlock("Rule", element("p", "solution-copy", result.ruleText));
  if (result.formula) appendSolutionBlock("Calculation method", element("p", "formula", result.formula));

  const steps = result.calculationSteps || result.reasoningSteps || result.explanationDetails?.reasoningSteps;
  if (steps?.length) {
    const list = document.createElement("ol");
    steps.forEach((step) => {
      const item = document.createElement("li");
      if (typeof step === "string") item.textContent = step;
      else {
        item.className = "calculation-step";
        item.append(element("strong", null, step.label || "Step"));
        if (step.formula) item.append(element("span", "formula", step.formula));
        if (step.substitution) item.append(element("span", null, ` · Substitute: ${step.substitution}`));
        if (step.result !== undefined) item.append(element("span", null, ` · Result: ${step.result}${step.unit ? ` ${step.unit}` : ""}`));
        if (step.note) item.append(element("span", null, ` · ${step.note}`));
      }
      list.append(item);
    });
    appendSolutionBlock("Step-by-step", list);
  }
  if (result.visualShortcut) appendSolutionBlock("Visual shortcut", element("p", "solution-copy", result.visualShortcut));
  if (result.evidenceSpans?.length) {
    const quotes = element("div");
    result.evidenceSpans.forEach((span) => quotes.append(element("blockquote", "evidence-quote", `“${span.text}” · paragraph ${span.paragraph}`)));
    appendSolutionBlock("Evidence from the passage", quotes);
  }
  if (result.correctOption) {
    appendSolutionBlock("Correct answer", element("p", "solution-copy", `Option ${result.correctOption}. ${result.correctReason || ""}`));
  }
  if (result.distractors?.length) {
    const list = element("ul", "distractor-list");
    result.distractors.forEach((item) => list.append(element("li", null, `Option ${item.option}: ${item.reason || item.description || "not supported"}`)));
    appendSolutionBlock("Why the other options fail", list);
  }
  hideButton.hidden = false;
  solutionPanel.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function appendSolutionBlock(title, content) {
  const block = element("div", "solution-block");
  block.append(element("h4", null, title), content);
  solutionContent.append(block);
}

async function revealSolution(optionId = selectedOption()) {
  if (!state.solutionToken) return;
  setStatus("Loading the solution…");
  try {
    const response = await fetch("/api/solution", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ solutionToken: state.solutionToken, selectedOption: optionId }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Solution unavailable");
    renderSolution(payload.solution);
    const selected = payload.solution.selectedOption;
    if (selected) {
      answerFeedback.textContent = payload.solution.isCorrect ? `Option ${selected} is correct.` : `Option ${selected} is recorded. Compare it with the worked solution below.`;
      answerFeedback.className = `answer-feedback ${payload.solution.isCorrect ? "correct" : "incorrect"}`;
    }
    setStatus("Solution is visible. Use Hide Solution to close it, or keep the toggle enabled for the next question.");
  } catch (error) {
    setStatus(error.message, true);
  }
}

function disableSolution() {
  setSolutionPreference(false);
  state.solution = null;
  solutionPanel.hidden = true;
  solutionContent.replaceChildren();
  solutionResult.textContent = "";
  hideButton.hidden = true;
  setStatus("Solution hidden. The preference is disabled for future questions.");
}

controlsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  fetchQuestion();
});
family.addEventListener("change", updateVariantOptions);
answerForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (state.solutionPreference) {
    setSolutionPreference(false);
    disableSolution();
  } else {
    setSolutionPreference(true);
    revealSolution();
  }
});
hideButton.addEventListener("click", disableSolution);
nextButton.addEventListener("click", () => {
  seed.value = String(Number(seed.value || 0) + 1);
  fetchQuestion();
});

updateVariantOptions();
fetchQuestion();
