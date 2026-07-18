"""Atomic JSON read/write helpers for the small state files under /data.

Writes go to a temp file and are renamed into place, so the web dashboard
never reads a half-written file while a scan is in progress.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def write_json(path: str, data: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_suffix(target.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2))
    os.replace(tmp_path, target)


def read_json(path: str) -> Any | None:
    target = Path(path)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except (ValueError, OSError):
        return None
