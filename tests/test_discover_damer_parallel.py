import sys
from pathlib import Path
import sqlite3

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import discover_damer_parallel as discovery


def test_segments_close_a_single_cycle_and_resume(tmp_path, monkeypatch):
    monkeypatch.setattr(discovery, "SEEDS", ("a", "m", "u"))
    pages = {"a": ["b", "m", "n"], "m": ["n", "u"], "u": ["v", "a"]}
    monkeypatch.setattr(discovery, "fetch", pages.__getitem__)
    path = tmp_path / "keys.sqlite"
    discovery.discover(path, 2)
    with sqlite3.connect(path) as db:
        assert {row[0] for row in db.execute("SELECT word FROM keys")} == {"a", "b", "m", "n", "u", "v"}
        assert db.execute("SELECT COUNT(*) FROM segments WHERE done = 1").fetchone()[0] == 3
    monkeypatch.setattr(discovery, "fetch", lambda word: pytest.fail("completed segment was fetched"))
    discovery.discover(path, 2)


import pytest
