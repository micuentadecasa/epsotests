# Inspectable visual examples

These are original EPSO-style abstract-reasoning items using the `five-option` exam profile: restrained vector figures, a sequence/matrix/analogy stimulus, five answer options (`A`–`E`), and exactly one correct option. They contain no textual logic puzzle. Each JSON item also includes an `actions.explainLogic` button contract so a learner can request the rule explanation without seeing it by default; the review result names every distractor failure.

Regenerate all files from the fixed seeds with:

```sh
python examples/visual/generate_examples.py
```

`manifest.json` is an index of the fixed-seed items. Each entry points to a complete portable JSON question and its SVG panel, and records the format, exam profile, seed, difficulty, serialized rules, correct option, explanation, and the `explainLogic` review action. The SVG panels are assembled from the package's existing `Scene`/`render_svg` output; the generator remains the source of truth.

| SVG | Format | Seed | Difficulty |
| --- | --- | --- | --- |
| `sequence-medium.svg` | sequence | 12 | medium |
| `matrix-2x2-easy.svg` | 2×2 matrix | 23 | easy |
| `matrix-3x3-hard.svg` | 3×3 matrix | 31 | hard |
| `analogy-hard.svg` | transformation analogy | 47 | hard |
