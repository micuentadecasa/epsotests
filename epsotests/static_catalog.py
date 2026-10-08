"""Deterministic catalog builder for the GitHub Pages learner app."""

from __future__ import annotations

from typing import Any

from . import (
    SUPPORTED_DIFFICULTIES,
    SUPPORTED_EXAM_PROFILES,
    SUPPORTED_FORMATS,
    SUPPORTED_NUMERICAL_FORMATS,
    SUPPORTED_NUMERICAL_OPERATIONS,
    SUPPORTED_VERBAL_QUESTION_TYPES,
    generate_numerical_question,
    generate_question,
    generate_verbal_question,
)
from .web_payload import public_question, static_solution

# Two adjacent fixed seeds make the Next Question control advance in a static
# catalog while keeping the artifact small. Unknown seeds select a stable entry
# from the same filtered set in the browser.
STATIC_CATALOG_SEEDS = (42, 43)


def _entry(
    family: str,
    variant: str,
    seed: int,
    difficulty: str,
    profile: str,
    question: dict[str, Any],
    representation: str | None = None,
) -> dict[str, Any]:
    public = public_question(question)
    key = ":".join(
        value
        for value in (family, variant, representation or "", difficulty, profile, str(seed))
        if value
    )
    return {
        "id": key,
        "family": family,
        "variant": variant,
        "representation": representation,
        "difficulty": difficulty,
        "profile": profile,
        "seed": seed,
        "question": public,
        "solution": static_solution(question),
    }


def generate_static_catalog() -> dict[str, Any]:
    """Generate all supported controls for a reproducible static artifact."""

    entries: list[dict[str, Any]] = []
    for difficulty in SUPPORTED_DIFFICULTIES:
        for profile in SUPPORTED_EXAM_PROFILES:
            for seed in STATIC_CATALOG_SEEDS:
                for format_name in SUPPORTED_FORMATS:
                    question = generate_question(
                        format_name,
                        seed=seed,
                        difficulty=difficulty,
                        exam_profile=profile,
                    )
                    entries.append(
                        _entry(
                            "visual",
                            format_name,
                            seed,
                            difficulty,
                            profile,
                            question,
                        )
                    )
                for operation in SUPPORTED_NUMERICAL_OPERATIONS:
                    for representation in SUPPORTED_NUMERICAL_FORMATS:
                        question = generate_numerical_question(
                            operation,
                            seed=seed,
                            difficulty=difficulty,
                            exam_profile=profile,
                            representation=representation,
                        )
                        entries.append(
                            _entry(
                                "numerical",
                                operation,
                                seed,
                                difficulty,
                                profile,
                                question,
                                representation,
                            )
                        )
                for question_type in SUPPORTED_VERBAL_QUESTION_TYPES:
                    question = generate_verbal_question(
                        question_type,
                        seed=seed,
                        difficulty=difficulty,
                        exam_profile=profile,
                    )
                    entries.append(
                        _entry(
                            "verbal",
                            question_type,
                            seed,
                            difficulty,
                            profile,
                            question,
                        )
                    )
    return {
        "version": 1,
        "seeds": list(STATIC_CATALOG_SEEDS),
        "questions": entries,
    }


if __name__ == "__main__":
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Generate the EPSO Pages question catalog")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(generate_static_catalog(), ensure_ascii=False, separators=(",", ":"))
        + "\n",
        encoding="utf-8",
    )
