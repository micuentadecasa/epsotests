# Inspectable verbal examples

These fixed-seed examples cover explicit reading comprehension, supported
inference, and true/false evaluation.  Every JSON item preserves the original
passage, paragraph boundaries, answer claims, character-addressable evidence
spans, option evaluations, distractor rationales, structured reasoning steps,
and the hidden `actions.explainLogic` / `Ver solución` review action.

The passages are original, concise EPSO-style material.  An evidence span's
`start` and `end` offsets address the exact quoted text in `passage.text`.
Claims distinguish explicit facts from unsupported or invalid inferences; a
wrong option is never treated as correct merely because it sounds plausible.

Companion SVG files are small exam-style inspection panels. Regenerate all
files from their fixed seeds with:

```sh
python examples/verbal/generate_examples.py
```

`manifest.json` indexes each complete question and panel, including its answer,
answer evidence, and Explain Logic action.
