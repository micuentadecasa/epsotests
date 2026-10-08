"""Command-line entry point for generating one visual abstract question."""

from __future__ import annotations

import argparse
import json

from .visual_abstract import generate_question


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic EPSO visual abstract question"
    )
    parser.add_argument(
        "format", choices=("sequence", "matrix-2x2", "matrix-3x3", "analogy")
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--difficulty", default="medium", choices=("easy", "medium", "hard")
    )
    args = parser.parse_args()
    print(
        json.dumps(
            generate_question(args.format, seed=args.seed, difficulty=args.difficulty),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
