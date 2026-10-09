"""Stable opaque signatures for question variation metadata."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def stable_signature(value: Any) -> str:
    """Return a deterministic short signature for JSON-shaped data."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:20]


__all__ = ["stable_signature"]
