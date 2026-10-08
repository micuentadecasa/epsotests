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
    ("sequence-medium", "sequence", 12, "medium"),
    ("matrix-2x2-easy", "matrix-2x2", 23, "easy"),
    ("matrix-3x3-hard", "matrix-3x3", 31, "hard"),
    ("analogy-hard", "analogy", 47, "hard"),
)


def _inner(svg: str) -> str:
    return svg.split(">", 1)[1].rsplit("</svg>", 1)[0]


def _figure(svg: str, x: int, y: int, size: int) -> str:
    scale = size / 160
    return f'<g transform="translate({x} {y}) scale({scale:g})">{_inner(svg)}</g>'


def _label(text: str, x: int, y: int, size: int = 16) -> str:
    escaped = html.escape(text, quote=True)
    return f'<text x="{x}" y="{y}" text-anchor="middle" font-family="sans-serif" font-size="{size}" fill="#111827">{escaped}</text>'


def _panel(question: dict[str, object]) -> str:
    fmt = str(question["format"])
    options = question["options"]
    option_svgs = [str(option["svg"]) for option in options]  # type: ignore[index]
    if fmt == "sequence":
        frames = question["stimulus"]["frames"]  # type: ignore[index]
        frame_svgs = [str(frame["svg"]) for frame in frames]  # type: ignore[index]
        frame_svgs.append("")
        width, height, size = 860, 500, 120
        parts = [_label("SEQUENCE", width // 2, 28, 18)]
        for index, svg in enumerate(frame_svgs):
            x = 30 + index * 160
            parts.append(f'<rect x="{x}" y="55" width="{size}" height="{size}" fill="#fff" stroke="#9ca3af"/>')
            parts.append(_label("?" if not svg else str(index + 1), x + size // 2, 202))
            if svg:
                parts.append(_figure(svg, x, 55, size))
        for index, svg in enumerate(option_svgs):
            x = 30 + index * 200
            parts.append(f'<rect x="{x}" y="270" width="{size}" height="{size}" fill="#fff" stroke="#9ca3af"/>')
            parts.append(_label(chr(65 + index), x + size // 2, 417))
            parts.append(_figure(svg, x, 270, size))
    elif fmt.startswith("matrix-"):
        grid = question["stimulus"]["grid"]  # type: ignore[index]
        rows = len(grid)  # type: ignore[arg-type]
        width, height, size = 900, 700 if rows == 3 else 520, 105
        parts = [_label(f"{rows} × {rows} MATRIX", width // 2, 28, 18)]
        grid_width = rows * (size + 12)
        grid_x = (width - grid_width) // 2
        for row, grid_row in enumerate(grid):  # type: ignore[union-attr]
            for column, figure in enumerate(grid_row):
                x = grid_x + column * (size + 12)
                y = 50 + row * (size + 12)
                parts.append(f'<rect x="{x}" y="{y}" width="{size}" height="{size}" fill="#fff" stroke="#9ca3af"/>')
                if figure is None:
                    parts.append(_label("?", x + size // 2, y + size // 2 + 8, 24))
                else:
                    parts.append(_figure(str(figure["svg"]), x, y, size))  # type: ignore[index]
        option_y = 80 + rows * (size + 12)
        for index, svg in enumerate(option_svgs):
            x = 30 + index * 215
            parts.append(f'<rect x="{x}" y="{option_y}" width="{size}" height="{size}" fill="#fff" stroke="#9ca3af"/>')
            parts.append(_label(chr(65 + index), x + size // 2, option_y + size + 24))
            parts.append(_figure(svg, x, option_y, size))
    else:
        left = question["stimulus"]["left"]  # type: ignore[index]
        target = question["stimulus"]["right"]["C"]  # type: ignore[index]
        width, height, size = 900, 500, 120
        parts = [_label("VISUAL ANALOGY", width // 2, 28, 18)]
        for label, figure, x in (
            ("A", left["A"], 80),  # type: ignore[index]
            ("B", left["B"], 270),  # type: ignore[index]
            ("C", target, 510),  # type: ignore[index]
        ):
            parts.append(_label(label, x + size // 2, 55))
            parts.append(_figure(str(figure["svg"]), x, 70, size))  # type: ignore[index]
        parts.append(_label("?", 750 + size // 2, 130, 24))
        for index, svg in enumerate(option_svgs):
            x = 30 + index * 215
            parts.append(f'<rect x="{x}" y="280" width="{size}" height="{size}" fill="#fff" stroke="#9ca3af"/>')
            parts.append(_label(chr(65 + index), x + size // 2, 427))
            parts.append(_figure(svg, x, 280, size))
    body = "".join(parts)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="EPSO visual abstract item">'
        f'<rect width="100%" height="100%" fill="#ffffff"/>{body}</svg>\n'
    )


def main() -> None:
    manifest: list[dict[str, object]] = []
    for filename, fmt, seed, difficulty in ITEMS:
        question = generate_question(fmt, seed=seed, difficulty=difficulty)
        (ROOT / f"{filename}.json").write_text(
            json.dumps(question, indent=2) + "\n", encoding="utf-8"
        )
        (ROOT / f"{filename}.svg").write_text(_panel(question), encoding="utf-8")
        manifest.append(
            {
                "json": f"{filename}.json",
                "svg": f"{filename}.svg",
                "format": question["format"],
                "seed": question["metadata"]["seed"],  # type: ignore[index]
                "difficulty": question["difficulty"],
                "correctOption": question["correctOption"],
                "rules": question["metadata"]["rules"],  # type: ignore[index]
                "explanation": question["explanation"],
            }
        )
    # manifest.json is the human-readable index; each entry points to the
    # complete portable question and its clean exam-style SVG panel.
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
