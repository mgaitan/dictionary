import sqlite3
import json

from fastapi.testclient import TestClient

from dictionary import damer
from dictionary.app import app
from tools import sync_damer_cache

ARTICLE = '<entry header="mate"><table><tr><td>mate.</td></tr><tr><td>I.</td><td>1.</td><td>Ar. Infusión de <i>yerba</i>.</td></tr></table></entry>'


def test_local_snapshot_avoids_remote(tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite"
    with sqlite3.connect(path) as db:
        db.execute(damer.SCHEMA)
        db.execute("INSERT INTO damer_articles VALUES (?, ?)", ("mate", "local"))
    monkeypatch.setattr(damer, "SNAPSHOT", path)
    monkeypatch.setattr(damer, "remote_sql", lambda *args: (_ for _ in ()).throw(AssertionError("remote called")))
    assert damer.get_article("mate") == "local"


def test_miss_fetches_and_caches_article(tmp_path, monkeypatch):
    monkeypatch.setattr(damer, "SNAPSHOT", tmp_path / "missing")
    calls = []
    def remote(sql, args=()):
        calls.append((sql, args))
        return []
    monkeypatch.setattr(damer, "remote_sql", remote)
    monkeypatch.setattr(damer, "fetch_article", lambda word: ARTICLE)
    result = damer.get_article("mate")
    assert json.loads(result)["entries"][0]["rows"][1] == ["I.", "1.", "Ar. Infusión de yerba."]
    assert calls[-1][1] == ("mate", result)


def test_parser_converts_html_to_text_rows():
    parsed = damer.parse_article('<entry header="x"><table><tr><td onclick="bad()">hola<script>alert(1)</script><img src=x></td></tr></table></entry>')
    assert parsed["entries"][0]["rows"] == [["hola"]]


def test_damer_result_in_site(monkeypatch):
    monkeypatch.setattr(damer, "get_article", lambda word: ARTICLE)
    response = TestClient(app).get("/?dict=damer&q=mate")
    assert response.status_code == 200
    assert "Infusión de yerba" in response.text
    assert "<entry" not in response.text
    assert "Americanismos (ASALE)" in response.text


def test_sync_preserves_existing_snapshot_on_failure(tmp_path, monkeypatch):
    path = tmp_path / "cache.sqlite"
    path.write_bytes(b"original")
    def remote(sql, args=()):
        if sql == damer.SCHEMA:
            return []
        raise RuntimeError("offline")
    monkeypatch.setattr(sync_damer_cache, "remote_sql", remote)
    import pytest
    with pytest.raises(RuntimeError):
        sync_damer_cache.sync(path)
    assert path.read_bytes() == b"original"
