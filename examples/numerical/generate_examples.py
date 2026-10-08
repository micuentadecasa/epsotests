"""Regenerate fixed-seed numerical EPSO examples and inspectable SVG panels."""

from __future__ import annotations

import html
import json
from pathlib import Path

from epsotests import generate_numerical_question


ROOT = Path(__file__).parent
ITEMS = (
    ("percentage-change-bar", "percentage-change", 12, "medium", "bar-chart", "five-option"),
    ("ratio-table", "ratio", 23, "easy", "table", "five-option"),
    ("growth-line", "growth", 31, "hard", "line-chart", "five-option"),
    ("multi-step-table", "multi-step", 47, "hard", "table", "five-option"),
)


def _inner(svg: str) -> str:
    return svg.split(">", 1)[1].rsplit("</svg>", 1)[0]


def _text(value: object, x: int, y: int, size: int = 15, anchor: str = "middle") -> str:
    return f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-family="sans-serif" font-size="{size}" fill="#111827">{html.escape(str(value), quote=True)}</text>'


def _table_panel(question: dict[str, object], x: int, y: int) -> list[str]:
    table = question["stimulus"]["table"]  # type: ignore[index]
    columns = table["columns"]
    rows = table["rows"]
    cell_width = 170
    parts = [_text(table.get("title", "Source data"), x + len(columns) * cell_width // 2, y - 12, 16)]
    for column_index, column in enumerate(columns):
        cx = x + column_index * cell_width
        parts.append(f'<rect x="{cx}" y="{y}" width="{cell_width}" height="30" fill="#e5e7eb" stroke="#6b7280"/>')
        parts.append(_text(column, cx + cell_width // 2, y + 20, 12))
    for row_index, row in enumerate(rows):
        for column_index, column in enumerate(columns):
            cx, cy = x + column_index * cell_width, y + 30 + row_index * 30
            parts.append(f'<rect x="{cx}" y="{cy}" width="{cell_width}" height="30" fill="#ffffff" stroke="#9ca3af"/>')
            parts.append(_text(row[column], cx + cell_width // 2, cy + 20, 12))
    return parts


def _panel(question: dict[str, object]) -> str:
    width, height = 1200, 560
    parts = [_text(f"1. {question['operation']}", width // 2, 28, 18), _text(question["question"], width // 2, 53, 14)]
    if question["format"] == "table":
        parts.extend(_table_panel(question, 80, 88))
    else:
        svg = question["stimulus"]["svg"]  # type: ignore[index]
        parts.append(f'<g transform="translate(280 68) scale(.9)">{_inner(svg)}</g>')
    parts.append(_text("Answer options", width // 2, 345, 15))
    options = question["options"]
    for index, option in enumerate(options):  # type: ignore[union-attr]
        x = 45 + index * 225
        parts.append(f'<rect x="{x}" y="365" width="190" height="72" rx="4" fill="#ffffff" stroke="#6b7280" stroke-width="2"/>')
        parts.append(_text(option["id"], x + 20, 393, 15))
        parts.append(_text(option["label"], x + 100, 408, 16))
    stem = html.escape(str(question["question"]), quote=True)
    body = "".join(parts)
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" data-format="{html.escape(str(question["format"]), quote=True)}" data-option-count="{len(options)}" aria-label="EPSO numerical item: {stem}"><rect width="100%" height="100%" fill="#ffffff"/>{body}</svg>\n'


def main() -> None:
    manifest: list[dict[str, object]] = []
    for filename, operation, seed, difficulty, representation, profile in ITEMS:
        question = generate_numerical_question(operation, seed=seed, difficulty=difficulty, representation=representation, exam_profile=profile)
        (ROOT / f"{filename}.json").write_text(json.dumps(question, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        (ROOT / f"{filename}.svg").write_text(_panel(question), encoding="utf-8")
        manifest.append({
            "json": f"{filename}.json",
            "svg": f"{filename}.svg",
            "operation": question["operation"],
            "format": question["format"],
            "examProfile": question["examProfile"],
            "itemNumber": question["itemNumber"],
            "seed": question["metadata"]["seed"],  # type: ignore[index]
            "difficulty": question["difficulty"],
            "correctOption": question["correctOption"],
            "formula": question["metadata"]["formula"],  # type: ignore[index]
            "calculationSteps": question["metadata"]["calculationSteps"],  # type: ignore[index]
            "explanation": question["explanation"],
            "explainLogic": question["actions"]["explainLogic"],  # type: ignore[index]
        })
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
