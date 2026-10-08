"""Command-line entry point for generating one visual abstract question."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .visual_abstract import (
    SUPPORTED_DIFFICULTIES,
    SUPPORTED_EXAM_PROFILES,
    SUPPORTED_FORMATS,
    generate_question,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser from the same contract as the Python API."""

    parser = argparse.ArgumentParser(
        description="Generate a deterministic EPSO visual abstract question"
    )
    parser.add_argument(
        "format",
        choices=SUPPORTED_FORMATS,
        help="visual item format to generate",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--difficulty",
        default="medium",
        choices=SUPPORTED_DIFFICULTIES,
        help="item difficulty (default: medium)",
    )
    parser.add_argument(
        "--exam-profile",
        default="standard",
        choices=SUPPORTED_EXAM_PROFILES,
        help="answer-option presentation profile (default: standard)",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="emit the Explain Logic review action and revealed result",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Print one complete, portable question JSON document to stdout."""

    args = build_parser().parse_args(argv)
    question = generate_question(
        args.format,
        seed=args.seed,
        difficulty=args.difficulty,
        exam_profile=args.exam_profile,
    )
    output: object = question
    if args.review:
        output = {
            "questionId": question["id"],
            "format": question["format"],
            "difficulty": question["difficulty"],
            "action": question["actions"]["explainLogic"],
        }
    print(json.dumps(output, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
