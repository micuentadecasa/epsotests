# epsotests

`epsotests` generates deterministic EPSO-style visual abstract-reasoning items. It
uses vector scenes and SVG figures only: no textual logic puzzles or image
runtime dependencies are involved.

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
  distractor metadata, explanation fragments, and the answer figure/signature.

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

## Command line

The installed `epsotests-visual` command and the module form emit one complete
question JSON document on stdout:

```sh
epsotests-visual sequence --seed 42 --difficulty medium
python -m epsotests.cli matrix-3x3 --seed 42 --difficulty hard
python -m epsotests.cli analogy --seed 42 --difficulty hard \
  --exam-profile five-option --review
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
