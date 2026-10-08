"""Regenerate the committed GitHub Pages question catalog."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from epsotests.static_catalog import generate_static_catalog


ROOT = Path(__file__).parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "epsotests" / "web" / "catalog.json",
        help="catalog JSON path (default: epsotests/web/catalog.json)",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    catalog = generate_static_catalog()
    args.output.write_text(
        json.dumps(catalog, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(catalog['questions'])} questions to {args.output}")


if __name__ == "__main__":
    main()
