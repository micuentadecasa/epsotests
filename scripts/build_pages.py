"""Build a relative-asset GitHub Pages artifact for the learner app."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from epsotests.static_catalog import generate_static_catalog


ROOT = Path(__file__).parents[1]
SOURCE = ROOT / "epsotests" / "web"


def build(output: Path) -> None:
    output = output.resolve()
    if output == SOURCE or SOURCE in output.parents:
        raise ValueError("Pages output must be outside the web source tree")
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    for name in ("app.css", "app.js"):
        shutil.copy2(SOURCE / name, output / name)

    index = (SOURCE / "index.html").read_text(encoding="utf-8")
    marker = 'data-epsotests-mode="api"'
    if marker not in index:
        raise ValueError("index.html is missing the deployment mode marker")
    (output / "index.html").write_text(
        index.replace(marker, 'data-epsotests-mode="static"'), encoding="utf-8"
    )

    catalog = generate_static_catalog()
    (output / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    (output / ".nojekyll").write_text("", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "_site")
    args = parser.parse_args()
    build(args.output)
    print(f"Built Pages artifact at {args.output}")


if __name__ == "__main__":
    main()
