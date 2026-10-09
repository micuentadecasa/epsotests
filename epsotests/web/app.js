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

const STATIC_MODE = document.documentElement.dataset.epsotestsMode === "static";
const STATIC_CATALOG_URL = new URL("catalog.json", document.baseURI);
// Keep the local API and the Pages catalog on the same deterministic question
// sequence. A session consumes each catalog position for the selected controls
// before the sequence is allowed to cycle after that catalog is exhausted.
const QUESTION_SEQUENCE_SEEDS = Object.freeze([42, 43]);
let staticCatalogPromise = null;

const state = {
  question: null,
  solutionToken: null,
  staticSolution: null,
  solution: null,
  solutionPreference: sessionStorage.getItem("epsotests:show-solution") === "true",
  loading: false,
  questionSequence: {
    seeds: QUESTION_SEQUENCE_SEEDS,
    seen: new Set(),
  },
};

const $ = (selector) => document.querySelector(selector);
const controlsForm = $("#controls-form");
const generateButton = controlsForm.querySelector('button[type="submit"]');
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
const questionSection = $("#question");
const itemMeta = $("#item-meta");
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

function setQuestionLoading(loading) {
  state.loading = loading;
  generateButton.disabled = loading;
  nextButton.disabled = loading;
  questionSection.setAttribute("aria-busy", String(loading));
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

function renderQuestion(
  question,
  token,
  staticSolution = null,
  { scrollToSolution = true } = {},
) {
  state.question = question;
  state.solutionToken = token;
  state.staticSolution = staticSolution;
  state.solution = null;
  const questionSeed = question.metadata?.seed ?? seed.value;
  seed.value = String(questionSeed);
  itemMeta.dataset.questionId = question.id || "";
  itemMeta.dataset.methodSignature = question.metadata?.methodSignature || "";
  itemMeta.dataset.answerSignature = question.metadata?.answerValueSignature || "";
  itemMeta.dataset.calculationSignature = question.metadata?.calculationSignature || "";
  itemMeta.dataset.evidenceSignature = question.metadata?.evidenceSignature || "";
  itemMeta.dataset.explanationSignature = question.metadata?.explanationSignature || "";
  itemMeta.textContent = `${question.exam} reasoning · ${question.id || `item ${question.itemNumber || 1}`} · seed ${questionSeed}`;
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
  if (state.solutionPreference) revealSolution("", { scrollToSolution });
}

function selectedOption() {
  return answerForm.querySelector("input[name=answer]:checked")?.value || "";
}

function questionParams() {
  const params = {
    family: family.value,
    difficulty: difficulty.value,
    profile: profile.value,
    seed: Number(seed.value || 0),
    variant: variant.value,
    representation: representation.value,
  };
  return params;
}

async function loadStaticCatalog() {
  if (!staticCatalogPromise) {
    staticCatalogPromise = fetch(STATIC_CATALOG_URL, { headers: { Accept: "application/json" } })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok || !Array.isArray(payload.questions)) {
          throw new Error(payload.error || "Static question catalog is unavailable");
        }
        return payload;
      });
  }
  return staticCatalogPromise;
}

function sequenceKey(params, sequenceSeed) {
  const key = [params.family, params.variant];
  if (params.family === "numerical") key.push(params.representation);
  key.push(params.difficulty, params.profile, sequenceSeed);
  return key.join(":");
}

function nextQuestionParams(params) {
  const { seeds, seen } = state.questionSequence;
  const nextSeed = seeds.find((candidate) => !seen.has(sequenceKey(params, candidate)));
  if (nextSeed !== undefined) return { ...params, seed: nextSeed };

  // The selected controls have consumed every available catalog position. Start
  // that deterministic catalog over without clearing history for other controls.
  seeds.forEach((candidate) => seen.delete(sequenceKey(params, candidate)));
  return { ...params, seed: seeds[0] };
}

function rememberQuestion(params, question, catalogEntry = null) {
  const questionSeed = question.metadata?.seed ?? params.seed;
  state.questionSequence.seen.add(
    catalogEntry?.id || sequenceKey(params, questionSeed),
  );
}

function staticCatalogEntry(catalog, params) {
  const candidates = catalog.questions.filter((entry) => (
    entry.family === params.family
    && entry.variant === params.variant
    && entry.difficulty === params.difficulty
    && entry.profile === params.profile
    && (params.family !== "numerical" || entry.representation === params.representation)
  ));
  if (!candidates.length) return null;
  const exact = candidates.find((entry) => entry.seed === params.seed);
  if (exact && !state.questionSequence.seen.has(exact.id)) return exact;
  const unseen = candidates.find((entry) => !state.questionSequence.seen.has(entry.id));
  if (unseen) return unseen;
  // The filtered catalog is exhausted. Keep selection deterministic while
  // allowing the next session cycle to begin at the requested catalog position.
  return exact || candidates[0];
}

async function fetchQuestion({ scrollToQuestion = false, advance = false } = {}) {
  if (state.loading) return;
  setQuestionLoading(true);
  setStatus("Generating a deterministic question…");
  const currentParams = questionParams();
  const params = advance ? nextQuestionParams(currentParams) : currentParams;
  seed.value = String(params.seed);
  const apiParams = new URLSearchParams({
    family: params.family,
    difficulty: params.difficulty,
    profile: params.profile,
    seed: String(params.seed),
  });
  if (params.family === "visual") apiParams.set("format", params.variant);
  if (params.family === "numerical") {
    apiParams.set("operation", params.variant);
    apiParams.set("representation", params.representation);
  }
  if (params.family === "verbal") apiParams.set("questionType", params.variant);
  try {
    if (STATIC_MODE) {
      const catalog = await loadStaticCatalog();
      const entry = staticCatalogEntry(catalog, params);
      if (!entry) throw new Error("No matching question in the static catalog");
      renderQuestion(entry.question, null, entry.solution, { scrollToSolution: false });
      rememberQuestion(params, entry.question, entry);
      if (scrollToQuestion) $("#question-prompt").scrollIntoView({ block: "start", behavior: "auto" });
      setStatus(`${entry.question.optionCount}-option question ready from the static catalog. Select an answer, then review the logic when you are ready.`);
      return;
    }
    const response = await fetch(`/api/question?${apiParams.toString()}`, { headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Question generation failed");
    renderQuestion(payload.question, payload.solutionToken, null, { scrollToSolution: false });
    rememberQuestion(params, payload.question);
    if (scrollToQuestion) $("#question-prompt").scrollIntoView({ block: "start", behavior: "auto" });
    setStatus(`${payload.question.optionCount}-option question ready. Select an answer, then review the logic when you are ready.`);
  } catch (error) {
    setStatus(error.message || "Question generation failed. Try again.", true);
  } finally {
    setQuestionLoading(false);
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

function renderSolution(result, { scrollToSolution = true } = {}) {
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
  if (scrollToSolution) {
    solutionPanel.scrollIntoView({ block: "nearest", behavior: "smooth" });
  } else {
    $("#question-prompt").scrollIntoView({ block: "start", behavior: "auto" });
  }
}

function appendSolutionBlock(title, content) {
  const block = element("div", "solution-block");
  block.append(element("h4", null, title), content);
  solutionContent.append(block);
}

async function revealSolution(optionId = selectedOption(), { scrollToSolution = true } = {}) {
  if (STATIC_MODE) {
    if (!state.staticSolution) return;
    const result = JSON.parse(JSON.stringify(state.staticSolution));
    result.selectedOption = optionId || null;
    result.isCorrect = optionId ? optionId === result.correctOption : null;
    result.selectedReason = result.isCorrect === true
      ? "Your answer matches the correct option."
      : optionId
        ? `You selected option ${optionId}; the correct answer is option ${result.correctOption}.`
        : "Solution preference is enabled. Select an answer to check your response.";
    renderSolution(result, { scrollToSolution });
    if (result.selectedOption) {
      answerFeedback.textContent = result.isCorrect ? `Option ${result.selectedOption} is correct.` : `Option ${result.selectedOption} is recorded. Compare it with the worked solution below.`;
      answerFeedback.className = `answer-feedback ${result.isCorrect ? "correct" : "incorrect"}`;
    }
    setStatus("Solution is visible. Use Hide Solution to close it, or keep the toggle enabled for the next question.");
    return;
  }
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
    renderSolution(payload.solution, { scrollToSolution });
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
  fetchQuestion({ advance: true });
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
nextButton.addEventListener("click", (event) => {
  event.preventDefault();
  fetchQuestion({ scrollToQuestion: true, advance: true });
});

updateVariantOptions();
fetchQuestion();
