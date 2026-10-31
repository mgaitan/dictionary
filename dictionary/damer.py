"""DAMER articles cached in Turso, with an optional local snapshot."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv

from dictionary.search import DATA_DIR

load_dotenv()
SNAPSHOT = DATA_DIR / "damer-cache.sqlite"
KEYS = DATA_DIR / "damer-keys-verified.sqlite"
SCHEMA = "CREATE TABLE IF NOT EXISTS damer_articles (word TEXT PRIMARY KEY, article TEXT NOT NULL)"
_lock = threading.Lock()
_last_request = 0.0


class ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries = []
        self.entry = None
        self.row = None
        self.cell = None
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.ignored += 1
        elif tag == "entry":
            self.entry = {"headword": dict(attrs).get("header", ""), "rows": []}
            self.entries.append(self.entry)
        elif tag == "tr" and self.entry is not None:
            self.row = []
        elif tag in {"td", "th"} and self.row is not None:
            self.cell = []
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.ignored:
            self.ignored -= 1
        elif tag in {"td", "th"} and self.cell is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.entry["rows"].append(self.row)
            self.row = None
        elif tag == "entry":
            self.entry = None

    def handle_data(self, data):
        if self.cell is not None and not self.ignored:
            self.cell.append(data)


def parse_article(article: str) -> dict:
    parser = ArticleParser()
    parser.feed(article)
    if not parser.entries or not any(entry["rows"] for entry in parser.entries):
        raise ValueError("El artículo de ASALE no contiene filas reconocibles")
    return {"version": 1, "entries": parser.entries}


def decode_article(article: str) -> dict:
    # Existing caches may contain the HTML stored by the first implementation.
    if article.lstrip().startswith("<"):
        return parse_article(article)
    result = json.loads(article)
    if result.get("version") != 1 or not isinstance(result.get("entries"), list):
        raise ValueError("Formato de artículo DAMER desconocido")
    return result


def remote_sql(sql: str, args: tuple[str, ...] = ()) -> list[tuple]:
    url = os.environ.get("DAMER_DATABASE_URL", "")
    token = os.environ.get("DAMER_AUTH_TOKEN", "")
    parts = urlsplit(url)
    scheme = "https" if parts.scheme == "libsql" else parts.scheme
    if scheme not in ("https", "http") or not parts.netloc or not token:
        raise RuntimeError("Configurá DAMER_DATABASE_URL y DAMER_AUTH_TOKEN")
    endpoint = urlunsplit((scheme, parts.netloc, "/v2/pipeline", "", ""))
    payload = {"requests": [{"type": "execute", "stmt": {"sql": sql, "args": [{"type": "text", "value": value} for value in args], "want_rows": True}}, {"type": "close"}]}
    response = httpx.post(endpoint, headers={"Authorization": "Bearer " + token}, json=payload, timeout=30)
    response.raise_for_status()
    result = response.json()["results"][0]
    if result["type"] == "error":
        raise RuntimeError("Error de Turso: " + result["error"].get("code", "unknown"))
    return [tuple(value.get("value") for value in row) for row in result["response"]["result"]["rows"]]


def fetch_article(word: str) -> str | None:
    global _last_request
    with _lock:
        time.sleep(max(0, 5 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        response = httpx.get("https://www.asale.org/damer/" + quote(word, safe=""), timeout=30, follow_redirects=True)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    articles = re.findall(r"<entry\b[^>]*>.*?</entry\s*>", response.text, re.I | re.S)
    return "\n".join(articles) if articles else None


def get_article(word: str) -> str | None:
    if SNAPSHOT.is_file():
        with sqlite3.connect(f"{SNAPSHOT.resolve().as_uri()}?mode=ro", uri=True) as db:
            row = db.execute("SELECT article FROM damer_articles WHERE word = ?", (word,)).fetchone()
            if row:
                return row[0]
    remote_sql(SCHEMA)
    rows = remote_sql("SELECT article FROM damer_articles WHERE word = ?", (word,))
    if rows:
        article = rows[0][0]
        if article.lstrip().startswith("<"):
            data = json.dumps(parse_article(article), ensure_ascii=False)
            remote_sql("UPDATE damer_articles SET article = ? WHERE word = ? AND article = ?", (data, word, article))
            return data
        return article
    article = fetch_article(word)
    if article:
        data = json.dumps(parse_article(article), ensure_ascii=False)
        remote_sql("INSERT INTO damer_articles (word, article) VALUES (?, ?) ON CONFLICT(word) DO NOTHING", (word, data))
        return data
    return None


def suggestions(query: str) -> list[str]:
    if not KEYS.is_file():
        return []
    with sqlite3.connect(f"{KEYS.resolve().as_uri()}?mode=ro", uri=True) as db:
        return [row[0] for row in db.execute("SELECT word FROM keys WHERE word LIKE ? ESCAPE '\\' ORDER BY word LIMIT 10", (query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",))]
