"""SQLite-backed dedupe store so we don't re-send the same alert every run.

Each (credential key id, bucket) pair is recorded once it has been notified.
"expired" alerts are re-sent periodically (see ``expired_reminder_interval_days``);
upcoming-expiry buckets (e.g. "30", "7") are only ever sent once, since the
next run will naturally move the credential into a smaller, still-unseen bucket.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    key_id TEXT NOT NULL,
    bucket TEXT NOT NULL,
    last_notified_at TEXT NOT NULL,
    PRIMARY KEY (key_id, bucket)
);
"""


class StateStore:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with closing(self._connect()) as conn:
            conn.execute(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path)

    def should_notify(self, key_id: str, bucket: str, expired_reminder_interval_days: int) -> bool:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT last_notified_at FROM notifications WHERE key_id = ? AND bucket = ?",
                (key_id, bucket),
            ).fetchone()
        if row is None:
            return True
        if bucket != "expired":
            return False
        last_notified_at = datetime.fromisoformat(row[0])
        return datetime.now(timezone.utc) - last_notified_at >= timedelta(
            days=expired_reminder_interval_days
        )

    def mark_notified(self, key_id: str, bucket: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as conn:
            conn.execute(
                "INSERT INTO notifications (key_id, bucket, last_notified_at) VALUES (?, ?, ?)\n"
                "ON CONFLICT(key_id, bucket) DO UPDATE SET "
                "last_notified_at = excluded.last_notified_at",
                (key_id, bucket, now),
            )
            conn.commit()

    def prune(self, active_key_ids: set[str]) -> int:
        """Remove state rows for credentials that no longer exist (rotated/deleted)."""
        with closing(self._connect()) as conn:
            existing = {row[0] for row in conn.execute("SELECT DISTINCT key_id FROM notifications")}
            stale = existing - active_key_ids
            if stale:
                conn.executemany(
                    "DELETE FROM notifications WHERE key_id = ?", [(k,) for k in stale]
                )
                conn.commit()
            return len(stale)
