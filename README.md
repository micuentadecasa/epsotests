# epsotests

## Visual abstract reasoning

`epsotests` generates deterministic EPSO abstract-reasoning questions as JSON with vector SVG figures. It supports visual sequences, 2x2 and 3x3 matrices, and transformation analogies. The JSON keeps the seed, serializable rules, scene figures, SVG options, distractor mutations, answer, and explanation for review or regeneration.

```python
from epsotests import generate_question

question = generate_question("matrix-3x3", seed=42, difficulty="hard")
print(question["correctOption"])
```

The same generator is available from the command line:

```sh
python -m epsotests.cli sequence --seed 42 --difficulty medium
```

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
