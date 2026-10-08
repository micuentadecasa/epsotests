# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- Add durable project-specific notes here as they are discovered through real work.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.

## Durable project notes

- The learner/review contract is implemented in `epsotests/visual_abstract.py`: generated items expose `actions.explainLogic`; `standard` uses four options and the checked-in fixtures use `five-option` (`A`–`E`); regenerate JSON/SVG examples with `python examples/visual/generate_examples.py`.
