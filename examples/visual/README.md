# Inspectable visual examples

These are original EPSO-style abstract-reasoning items: restrained vector figures, a sequence/matrix/analogy stimulus, four answer options, and exactly one correct option. They contain no textual logic puzzle.

Regenerate all files from the fixed seeds with:

```sh
python examples/visual/generate_examples.py
```

`manifest.json` records each source question's format, seed, difficulty, serialized rules, correct option, and explanation. The SVG panels are assembled from the package's existing `Scene`/`render_svg` output; the generator remains the source of truth.

| SVG | Format | Seed | Difficulty |
| --- | --- | --- | --- |
| `sequence-medium.svg` | sequence | 12 | medium |
| `matrix-2x2-easy.svg` | 2×2 matrix | 23 | easy |
| `matrix-3x3-hard.svg` | 3×3 matrix | 31 | hard |
| `analogy-hard.svg` | transformation analogy | 47 | hard |
