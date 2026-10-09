# epsotests

`epsotests` generates deterministic EPSO-style visual abstract-, numerical-,
and verbal-reasoning items. It uses dependency-free vector scenes, charts, and
passages with portable JSON; no browser, image runtime, or remote service is
required.

## Generate an item in Python

```python
from epsotests import generate_question

question = generate_question(
    "matrix-3x3", seed=42, difficulty="hard", exam_profile="five-option"
)
print(question["correctOption"])
```

The canonical formats are `sequence`, `matrix-2x2`, `matrix-3x3`, and
`analogy` (a transformation analogy). The canonical difficulty values are
`easy`, `medium`, and `hard`. The `standard` exam profile matches the
four-option computer/PDF style; `five-option` matches the five-option A–E
exam-sheet style used by the checked-in fixtures.

Each returned question is portable JSON containing:

- a visual `stimulus` with serialized scenes and deterministic SVG figures;
- exactly four options (`A`–`D`) by default, or the option count selected by
  an `exam_profile` (the included `five-option` profile uses `A`–`E`), each
  with a serialized `figure`, SVG, and visual `mutation` record;
- one `correctOption` and a human-readable `explanation`;
- an `actions.explainLogic` button contract. It is hidden by default and
  reveals the rule, answer reasoning, and one failure reason for every
  distractor only after the learner requests it;
- `metadata` containing the seed, serialized rules, generated figures,
  distractor metadata, explanation fragments, the answer figure/signature,
  and opaque method/answer/explanation signatures used to audit variation.

Adjacent catalog seeds select explicit visual rule profiles (rotation/movement,
reflection/fill, count/symmetry, and nesting/shape), so a new drawing is not
just a cosmetic change. Numerical items likewise record operation and
calculation signatures; verbal items record evidence-path signatures.

Rules can be supplied for controlled fixtures and difficulty tuning:

```python
from epsotests import Rule, generate_sequence

question = generate_sequence(
    seed=7,
    rules=[Rule("composite", {"rules": [
        Rule("rotation", {"degrees": 90}),
        Rule("translation", {"dx": 0.08, "dy": 0.04}),
    ]})],
)
```

## Numerical reasoning

Numerical questions preserve their source table, chart data, formulas,
substitutions, intermediate values, units, rounding, visual shortcuts, and
specific distractor rationales. Supported operations are percentage change,
ratios, proportions, totals, growth, comparisons, and multi-step calculations.
They use the same four-option `standard` and five-option `five-option` profiles
and hidden `Explain Logic` / `Ver solución` action contract as visual items.
Each operation has explicit calculation templates, so adjacent seeds change
both the worked path and the answer value:

```python
from epsotests import generate_numerical_question

question = generate_numerical_question(
    "percentage-change", seed=42, representation="bar-chart", exam_profile="five-option"
)
print(question["correctOption"], question["metadata"]["calculationSteps"])
```

Chart items include accessible deterministic SVG; table items include an
HTML-friendly `<table>`. Fixed-seed JSON and exam-style SVG panels are in
[`examples/numerical/`](examples/numerical/), regenerated with:

```sh
python examples/numerical/generate_examples.py
```

## Verbal reasoning

Verbal questions preserve an original reading-comprehension passage, candidate
claims, exact character-addressable evidence spans, answer evaluations, and
specific distractor rationales. Supported types are `reading-comprehension`,
`inference`, and `true-false`; they use the same four-option `standard` and
five-option `five-option` profiles and hidden `Explain Logic` / `Ver solución`
action contract:

```python
from epsotests import generate_verbal_question

question = generate_verbal_question(
    "inference", seed=42, difficulty="hard", exam_profile="five-option"
)
print(question["correctOption"], question["metadata"]["answerEvidence"])
```

Evidence spans point back into `passage.text`, while claims and explanation
steps distinguish explicit facts from unsupported inferences. Fixed-seed JSON
and exam-style SVG panels are in [`examples/verbal/`](examples/verbal/),
regenerated with:

```sh
python examples/verbal/generate_examples.py
```

## Command line

The installed `epsotests-visual` command and the module form emit one complete
question JSON document on stdout:

```sh
epsotests-visual sequence --seed 42 --difficulty medium
python -m epsotests.cli matrix-3x3 --seed 42 --difficulty hard
python -m epsotests.cli analogy --seed 42 --difficulty hard \
  --exam-profile five-option --review
python -m epsotests.cli numerical percentage-change --seed 42 --representation bar-chart
epsotests-verbal inference --seed 42 --difficulty hard --exam-profile five-option
python -m epsotests.cli verbal true-false --seed 42
```

Use one of the four canonical format names and one of `easy`, `medium`, or
`hard`. The default `standard` exam profile emits four `A`–`D` options; use
`--exam-profile five-option` for five `A`–`E` options. Repeating a command with
the same format, seed, difficulty, and profile produces identical JSON and SVG
output. `--review` emits the explicit Explain Logic button action and its
revealed review result for a reviewer or learner UI.

The reusable action shape is:

```json
{
  "id": "explain-logic",
  "type": "button",
  "label": "Explain logic",
  "initiallyVisible": false,
  "revealsAnswer": true,
  "solutionView": {
    "initiallyVisible": false,
    "hideAction": {
      "id": "hide-solution",
      "type": "button",
      "label": "Hide solution",
      "visibleAfterReveal": true
    }
  },
  "result": {
    "optionCount": 5,
    "rule": [],
    "ruleText": "...",
    "explanation": "...",
    "correctOption": "A",
    "correctReason": "...",
    "distractors": []
  }
}
```

Python consumers can obtain the revealed result after the learner activates
that control with `explain_logic(question)`. Profiles are available as
`EXAM_PROFILES`, or callers can pass `ExamProfile("custom", 6)` for another
exam-specific option count.

## Inspectable examples

The checked-in [`examples/visual/`](examples/visual/) directory contains one
fixed-seed JSON question and one exam-style SVG panel for each format. The JSON
is the complete review/regeneration record; `manifest.json` indexes each JSON
and SVG pair with its format, exam profile, seed, difficulty, rules, answer,
explanation, and Explain Logic review action.

Regenerate and inspect all examples with:

```sh
python examples/visual/generate_examples.py
```

The generator remains the source of truth, so regeneration should leave the
checked-in files unchanged. The local end-to-end suite also parses the generated
SVG and checks option uniqueness, metadata, explanations, and CLI output:

```sh
python -m unittest discover -v
```

## Learner web app

A local learner-facing app serves the same deterministic Python generators
through a thin JSON API. The browser never reimplements question rules: it
requests a sanitized question, submits the selected option, and asks the
server for the Explain Logic / Ver solución review payload.

Install the package and start the app from the repository root:

```sh
python -m pip install --editable .
python -m epsotests.web_server --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Choose visual abstract, numerical, or verbal
reasoning, then set the format, difficulty, seed, and standard/five-option
profile. Generate Question and Next Question share one deterministic session
sequence, consuming each available catalog position for the selected controls
before cycling. The solution toggle is session-persistent: enabling it
automatically opens the solution for each Next Question until Hide Solution /
Ocultar solución is selected.

Run the browser behavior and accessibility tests with Playwright:

```sh
cd web
npm install
npx playwright install chromium
npm test
```

The Playwright configuration starts the local server automatically on port
8765. The API can also be checked directly at `/api/health`.

### GitHub Pages static deployment

GitHub Pages serves the browser app from a repository subpath and cannot run
the Python API. The Pages build therefore creates `catalog.json` from fixed
seeds (`42` and `43`) for every visual, numerical, and verbal variant,
difficulty, representation, and option profile. The browser switches to this
catalog through the static build flag; it does not call `/api` in that mode.
The same app and controls continue to use the Python API in local mode.

Build and preview the static artifact locally from the repository root:

```sh
python -m pip install --editable .
python scripts/build_pages.py --output _site
python -m http.server 8000 --directory _site
```

Open <http://127.0.0.1:8000/>. To regenerate only the committed catalog,
run `python examples/web/generate_catalog.py`; the reproducibility and asset
integrity checks are included in `python -m unittest discover -v`.

The deployment workflow is `.github/workflows/pages.yml`. It runs on pushes to
`main` (or `workflow_dispatch`), generates the catalog and relative-asset
artifact, uploads it with `actions/upload-pages-artifact`, and deploys it with
`actions/deploy-pages`. After enabling GitHub Pages with **GitHub Actions** as
the source, the URL is:

```text
https://<owner>.github.io/<repository>/
```

Run the Pages-mode browser smoke tests locally with:

```sh
cd web
EPSOTESTS_STATIC=1 npm test
```

Those tests serve the artifact under `/epsotests/`, covering relative asset
resolution, no-API loading, answer selection, persistent Explain Logic / Ver
solución review, Hide Solution, Next Question, and one flow per exam family.
