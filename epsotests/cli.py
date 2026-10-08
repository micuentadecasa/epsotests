"""Command-line entry point for generating one visual abstract question."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .numerical import (
    SUPPORTED_NUMERICAL_FORMATS,
    SUPPORTED_NUMERICAL_OPERATIONS,
    generate_numerical_question,
)
from .visual_abstract import (
    SUPPORTED_DIFFICULTIES,
    SUPPORTED_EXAM_PROFILES,
    SUPPORTED_FORMATS,
    generate_question,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser from the same contract as the Python API."""

    parser = argparse.ArgumentParser(
        description="Generate a deterministic EPSO visual abstract or numerical question"
    )
    parser.add_argument(
        "format",
        choices=SUPPORTED_FORMATS + SUPPORTED_NUMERICAL_OPERATIONS + ("numerical",),
        help="visual format, numerical operation, or 'numerical' followed by an operation",
    )
    parser.add_argument(
        "operation",
        nargs="?",
        choices=SUPPORTED_NUMERICAL_OPERATIONS,
        help="numerical operation when the format is 'numerical'",
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
        "--representation",
        choices=SUPPORTED_NUMERICAL_FORMATS,
        help="numerical table, bar-chart, or line-chart representation",
    )
    parser.add_argument(
        "--review",
        action="store_true",
        help="emit the Explain Logic / Ver solución review action and revealed result",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> None:
    """Print one complete, portable question JSON document to stdout."""

    args = build_parser().parse_args(argv)
    if args.format == "numerical" or args.format in SUPPORTED_NUMERICAL_OPERATIONS:
        operation = args.operation or (args.format if args.format != "numerical" else None)
        if operation is None:
            raise SystemExit("the numerical command needs an operation")
        question = generate_numerical_question(
            operation,
            seed=args.seed,
            difficulty=args.difficulty,
            exam_profile=args.exam_profile,
            representation=args.representation,
        )
    else:
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
