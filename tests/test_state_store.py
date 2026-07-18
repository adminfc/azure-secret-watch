from __future__ import annotations

from datetime import datetime, timedelta, timezone

from azure_secret_watch.state_store import StateStore


def test_first_notification_always_sent(state_db_path):
    store = StateStore(state_db_path)
    assert store.should_notify("key-1", "14", expired_reminder_interval_days=7) is True


def test_non_expired_bucket_not_resent(state_db_path):
    store = StateStore(state_db_path)
    store.mark_notified("key-1", "14")
    assert store.should_notify("key-1", "14", expired_reminder_interval_days=7) is False
    # A different (smaller) bucket for the same credential is a fresh alert.
    assert store.should_notify("key-1", "7", expired_reminder_interval_days=7) is True


def test_expired_bucket_resent_after_interval(state_db_path):
    store = StateStore(state_db_path)
    store.mark_notified("key-1", "expired")
    assert store.should_notify("key-1", "expired", expired_reminder_interval_days=7) is False

    # Simulate time passing by writing an old timestamp directly.
    import sqlite3

    old_ts = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    with sqlite3.connect(state_db_path) as conn:
        conn.execute(
            "UPDATE notifications SET last_notified_at = ? WHERE key_id = ? AND bucket = ?",
            (old_ts, "key-1", "expired"),
        )
        conn.commit()

    assert store.should_notify("key-1", "expired", expired_reminder_interval_days=7) is True


def test_prune_removes_stale_credentials(state_db_path):
    store = StateStore(state_db_path)
    store.mark_notified("key-old", "14")
    store.mark_notified("key-active", "7")

    removed = store.prune(active_key_ids={"key-active"})

    assert removed == 1
    assert store.should_notify("key-old", "14", expired_reminder_interval_days=7) is True
    assert store.should_notify("key-active", "7", expired_reminder_interval_days=7) is False
