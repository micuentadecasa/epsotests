"""Regenerate fixed-seed verbal EPSO examples and inspectable SVG panels."""

from __future__ import annotations

import html
import json
from pathlib import Path

from epsotests import generate_verbal_question


ROOT = Path(__file__).parent
ITEMS = (
    ("permit-reading", "reading-comprehension", 5, "medium", "five-option"),
    ("river-inference", "inference", 10, "hard", "five-option"),
    ("archive-true-false", "true-false", 9, "easy", "five-option"),
    ("queue-inference", "inference", 0, "hard", "five-option"),
)


def _text(value: object, x: int, y: int, size: int = 15, anchor: str = "start", weight: str = "normal") -> str:
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="#111827">'
        f"{html.escape(str(value), quote=True)}</text>"
    )


def _wrapped(value: str, width: int = 105) -> list[str]:
    words = value.split()
    lines: list[str] = []
    current = ""
    for word in words:
        if current and len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def _panel(question: dict[str, object]) -> str:
    width, height = 1400, 760
    parts = [
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        _text(f"1. {question['questionType']}", width // 2, 30, 20, "middle", "bold"),
        _text(question["question"], width // 2, 58, 15, "middle"),
        _text(question["passage"]["title"], 50, 96, 17, "start", "bold"),  # type: ignore[index]
    ]
    y = 122
    for paragraph in question["passage"]["paragraphs"]:  # type: ignore[index]
        for line in _wrapped(str(paragraph)):
            parts.append(_text(line, 50, y, 13))
            y += 20
        y += 9
    parts.append(_text("Answer options", 50, 420, 16, "start", "bold"))
    options = question["options"]
    option_y = 446
    for option in options:  # type: ignore[union-attr]
        parts.append(f'<rect x="50" y="{option_y - 20}" width="1300" height="42" rx="4" fill="#ffffff" stroke="#9ca3af"/>')
        parts.append(_text(f"{option['id']}. {option['text']}", 66, option_y + 7, 13))  # type: ignore[index]
        option_y += 52
    body = "".join(parts)
    aria = html.escape(f"EPSO verbal item: {question['question']}", quote=True)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" data-format="verbal" '
        f'data-question-type="{html.escape(str(question["questionType"]), quote=True)}" '
        f'data-option-count="{len(options)}" aria-label="{aria}">{body}</svg>\n'
    )


def main() -> None:
    manifest: list[dict[str, object]] = []
    for filename, question_type, seed, difficulty, profile in ITEMS:
        question = generate_verbal_question(
            question_type,
            seed=seed,
            difficulty=difficulty,
            exam_profile=profile,
        )
        (ROOT / f"{filename}.json").write_text(
            json.dumps(question, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (ROOT / f"{filename}.svg").write_text(_panel(question), encoding="utf-8")
        manifest.append(
            {
                "json": f"{filename}.json",
                "svg": f"{filename}.svg",
                "questionType": question["questionType"],
                "format": question["format"],
                "examProfile": question["examProfile"],
                "itemNumber": question["itemNumber"],
                "seed": question["metadata"]["seed"],  # type: ignore[index]
                "difficulty": question["difficulty"],
                "correctOption": question["correctOption"],
                "answerEvidence": question["metadata"]["answerEvidence"],  # type: ignore[index]
                "explanation": question["explanation"],
                "explainLogic": question["actions"]["explainLogic"],  # type: ignore[index]
            }
        )
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
