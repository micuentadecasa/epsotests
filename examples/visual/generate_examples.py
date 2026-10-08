"""Regenerate the checked-in EPSO-style visual item examples.

The source questions remain the package's JSON contract.  This small adapter
only lays their existing SVG figures out as a restrained exam-style panel; it
does not introduce another scene model or any text-puzzle logic.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from epsotests import generate_question


ROOT = Path(__file__).parent
ITEMS = (
    ("sequence-medium", "sequence", 12, "medium", "five-option"),
    ("matrix-2x2-easy", "matrix-2x2", 23, "easy", "five-option"),
    ("matrix-3x3-hard", "matrix-3x3", 31, "hard", "five-option"),
    ("analogy-hard", "analogy", 47, "hard", "five-option"),
)


def _inner(svg: str) -> str:
    return svg.split(">", 1)[1].rsplit("</svg>", 1)[0]


def _figure(svg: str, x: int, y: int, size: int) -> str:
    scale = size / 160
    return f'<g transform="translate({x} {y}) scale({scale:g})">{_inner(svg)}</g>'


def _label(text: str, x: int, y: int, size: int = 16) -> str:
    escaped = html.escape(text, quote=True)
    return f'<text x="{x}" y="{y}" text-anchor="middle" font-family="sans-serif" font-size="{size}" fill="#111827">{escaped}</text>'


def _box(x: int, y: int, size: int) -> str:
    return f'<rect x="{x}" y="{y}" width="{size}" height="{size}" fill="#ffffff" stroke="#6b7280" stroke-width="2"/>'


def _header(question: dict[str, object], title: str, width: int) -> list[str]:
    item_number = int(question.get("itemNumber", 1))
    return [
        _label(f"{item_number}. {title}", width // 2, 26, 18),
        _label(str(question["question"]), width // 2, 49, 14),
    ]


def _option_row(option_svgs: list[str], y: int, size: int, width: int) -> list[str]:
    parts = [_label("Answer options", width // 2, y - 18, 15)]
    for index, svg in enumerate(option_svgs):
        x = 35 + index * 220
        parts.append(_box(x, y, size))
        parts.append(_label(chr(65 + index), x + size // 2, y + size + 23))
        parts.append(_figure(svg, x, y, size))
    return parts


def _panel(question: dict[str, object]) -> str:
    fmt = str(question["format"])
    options = question["options"]
    option_svgs = [str(option["svg"]) for option in options]  # type: ignore[index]
    if fmt == "sequence":
        frames = question["stimulus"]["frames"]  # type: ignore[index]
        frame_svgs = [str(frame["svg"]) for frame in frames]  # type: ignore[index]
        frame_svgs.append("")
        width, height, size = 1150, 470, 110
        parts = _header(question, "Complete the visual sequence", width)
        for index, svg in enumerate(frame_svgs):
            x = 35 + index * 220
            y = 70
            parts.append(_box(x, y, size))
            parts.append(_label("?" if not svg else str(index + 1), x + size // 2, y + size + 22))
            if svg:
                parts.append(_figure(svg, x, y, size))
        parts.extend(_option_row(option_svgs, 285, size, width))
    elif fmt.startswith("matrix-"):
        grid = question["stimulus"]["grid"]  # type: ignore[index]
        rows = len(grid)  # type: ignore[arg-type]
        size = 105
        width, height = 1200, 520 if rows == 2 else 640
        parts = _header(question, f"Complete the {rows} × {rows} matrix", width)
        grid_width = rows * (size + 12)
        grid_x = (width - grid_width) // 2
        for row, grid_row in enumerate(grid):  # type: ignore[union-attr]
            for column, figure in enumerate(grid_row):
                x = grid_x + column * (size + 12)
                y = 65 + row * (size + 12)
                parts.append(_box(x, y, size))
                if figure is None:
                    parts.append(_label("?", x + size // 2, y + size // 2 + 8, 24))
                else:
                    parts.append(_figure(str(figure["svg"]), x, y, size))  # type: ignore[index]
        option_y = 350 if rows == 2 else 465
        parts.extend(_option_row(option_svgs, option_y, size, width))
    else:
        left = question["stimulus"]["left"]  # type: ignore[index]
        target = question["stimulus"]["right"]["C"]  # type: ignore[index]
        width, height, size = 1200, 520, 105
        parts = _header(question, "Complete the visual analogy", width)
        for label, figure, x in (
            ("A", left["A"], 145),  # type: ignore[index]
            ("B", left["B"], 365),  # type: ignore[index]
            ("C", target, 700),  # type: ignore[index]
        ):
            y = 75
            parts.append(_box(x, y, size))
            parts.append(_label(label, x + size // 2, y + size + 22))
            parts.append(_figure(str(figure["svg"]), x, y, size))  # type: ignore[index]
        missing_x = 920
        parts.append(_box(missing_x, 75, size))
        parts.append(_label("?", missing_x + size // 2, 75 + size // 2 + 8, 24))
        parts.extend(_option_row(option_svgs, 300, size, width))
    body = "".join(parts)
    stem = html.escape(str(question["question"]), quote=True)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" data-format="{html.escape(fmt)}" '
        f'data-item-number="{question.get("itemNumber", 1)}" data-option-count="{len(option_svgs)}" '
        f'aria-label="EPSO visual abstract item: {stem}">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>{body}</svg>\n'
    )


def main() -> None:
    manifest: list[dict[str, object]] = []
    for filename, fmt, seed, difficulty, exam_profile in ITEMS:
        question = generate_question(
            fmt,
            seed=seed,
            difficulty=difficulty,
            exam_profile=exam_profile,
        )
        (ROOT / f"{filename}.json").write_text(
            json.dumps(question, indent=2) + "\n", encoding="utf-8"
        )
        (ROOT / f"{filename}.svg").write_text(_panel(question), encoding="utf-8")
        manifest.append(
            {
                "json": f"{filename}.json",
                "svg": f"{filename}.svg",
                "format": question["format"],
                "examProfile": question["examProfile"],
                "itemNumber": question["itemNumber"],
                "seed": question["metadata"]["seed"],  # type: ignore[index]
                "difficulty": question["difficulty"],
                "correctOption": question["correctOption"],
                "rules": question["metadata"]["rules"],  # type: ignore[index]
                "explanation": question["explanation"],
                "explainLogic": question["actions"]["explainLogic"],  # type: ignore[index]
            }
        )
    # manifest.json is the human-readable index; each entry points to the
    # complete portable question and its clean exam-style SVG panel.
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
