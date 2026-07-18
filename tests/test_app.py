from __future__ import annotations

from datetime import datetime, timedelta, timezone

import azure_secret_watch.app as app
from azure_secret_watch.cache import read_json, write_json
from tests.conftest import make_config


def _iso(hours_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _entry(hours_ago: float) -> dict:
    return {
        "status": "ok",
        "detail": "",
        "alert_count": 0,
        "credential_count": 1,
        "app_count": 1,
        "ran_at": _iso(hours_ago),
    }


def test_record_run_result_drops_entries_older_than_a_day(tmp_path):
    config = make_config(tmp_path)
    write_json(config.scan_history_file_path, [_entry(2), _entry(30)])

    app._record_run_result(config, "ok", "", 0, 1, 1)

    history = read_json(config.scan_history_file_path)
    assert len(history) == 2
    assert all(
        datetime.now(timezone.utc) - datetime.fromisoformat(h["ran_at"]) <= timedelta(days=1)
        for h in history
    )


def test_record_run_result_still_caps_by_scan_history_limit(tmp_path):
    config = make_config(tmp_path, scan_history_limit=2)
    write_json(config.scan_history_file_path, [_entry(1), _entry(2)])

    app._record_run_result(config, "ok", "", 0, 1, 1)

    history = read_json(config.scan_history_file_path)
    assert len(history) == 2
