from pathlib import Path

from fa.cache import read_json, write_json


def test_read_missing_returns_empty_dict(tmp_path: Path):
    missing = tmp_path / "does_not_exist.json"
    assert read_json(missing) == {}


def test_write_then_read_roundtrip(tmp_path: Path):
    payload = {"seen_hashes": ["h1"]}
    path = tmp_path / "cache.json"
    write_json(path, payload)
    assert read_json(path) == payload
