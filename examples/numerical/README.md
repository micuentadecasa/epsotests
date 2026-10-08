# Inspectable numerical examples

These fixed-seed examples cover percentage change, ratios, compound growth, and
multi-step calculations. They use the same five-option (`A`–`E`) exam profile as
the checked-in visual fixtures.

Each JSON file preserves the source table, chart/table representation, formula,
substitution and intermediate calculation steps, rounded result, distractor
rationale, and hidden `actions.explainLogic` / `Ver solución` review action.
Chart questions include accessible vector SVG in the JSON; table questions
include an HTML-friendly table representation. The companion SVG panels are
small exam-style inspection views.

Regenerate all files from their fixed seeds with:

```sh
python examples/numerical/generate_examples.py
```

`manifest.json` indexes the complete question JSON and panel SVG for each item.
