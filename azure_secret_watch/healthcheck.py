"""Docker HEALTHCHECK probe.

Reads the status file written after each scan (see app._write_status) and
exits non-zero only if the most recent run recorded an error. Before the
first scheduled run there is nothing to report yet, so a missing file is
treated as healthy.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    status_path = os.getenv("STATUS_FILE_PATH", "/data/last_run.json")
    path = Path(status_path)
    if not path.exists():
        return 0
    try:
        data = json.loads(path.read_text())
    except (ValueError, OSError):
        # Corrupt/unreadable status file shouldn't flap the container health.
        return 0
    return 0 if data.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
