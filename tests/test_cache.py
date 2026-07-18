from __future__ import annotations

from azure_secret_watch.cache import read_json, write_json


def test_write_then_read_round_trip(tmp_path):
    path = str(tmp_path / "sub" / "data.json")
    write_json(path, {"a": 1, "b": [1, 2, 3]})
    assert read_json(path) == {"a": 1, "b": [1, 2, 3]}


def test_read_json_missing_file_returns_none(tmp_path):
    assert read_json(str(tmp_path / "missing.json")) is None


def test_read_json_corrupt_file_returns_none(tmp_path):
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json")
    assert read_json(str(path)) is None


def test_write_json_no_tmp_file_left_behind(tmp_path):
    path = tmp_path / "data.json"
    write_json(str(path), {"x": 1})
    assert path.exists()
    assert not path.with_suffix(".json.tmp").exists()
