# /// script
# dependencies = ["httpx>=0.27,<1", "python-dotenv>=1,<2"]
# ///
"""Upload Moliner to the libSQL database in .env using bounded bulk inserts.

Usage: uv run tools/upload_moliner.py [--resume]
Requires an empty destination, or --resume with the same source fingerprint.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
TABLES = ("metadata", "entries", "senses", "search_terms", "articles", "xml_ids")


def sql_value(value) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    return "'" + value.replace("'", "''") + "'"


def insert_batches(database, table: str, max_bytes: int = 1_000_000):
    columns = [row[1] for row in database.execute(f'PRAGMA table_info("{table}")')]
    names = ",".join('"' + name + '"' for name in ["rowid", *columns])
    prefix = f'INSERT OR IGNORE INTO "{table}" ({names}) VALUES '
    values = []
    size = len(prefix)
    for row in database.execute(f'SELECT rowid,* FROM "{table}" ORDER BY rowid'):
        literal = "(" + ",".join(sql_value(value) for value in row) + ")"
        length = len(literal.encode("utf-8")) + 1
        if values and (size + length > max_bytes or len(values) >= 10_000):
            yield prefix + ",".join(values), len(values)
            values = []
            size = len(prefix)
        values.append(literal)
        size += length
    if values:
        yield prefix + ",".join(values), len(values)


class SqlHttp:
    def __init__(self, url: str, token: str):
        parts = urlsplit(url)
        scheme = "https" if parts.scheme == "libsql" else parts.scheme
        if scheme not in ("https", "http") or not parts.netloc:
            raise ValueError("Invalid MOLINER_DATABASE_URL")
        self.url = urlunsplit((scheme, parts.netloc, "/v2/pipeline", "", ""))
        self.client = httpx.Client(
            headers={"Authorization": "Bearer " + token},
            timeout=httpx.Timeout(120, connect=20),
        )
        self.requests = 0

    def execute(self, sql: str):
        payload = {
            "requests": [
                {"type": "execute", "stmt": {"sql": sql, "want_rows": True}},
                {"type": "close"},
            ]
        }
        # Inserts retain source rowids and ignore conflicts: retries are idempotent.
        for attempt in range(4):
            try:
                response = self.client.post(self.url, json=payload)
                self.requests += 1
                if response.status_code in (429, 502, 503, 504) and attempt < 3:
                    time.sleep(2**attempt)
                    continue
                if response.status_code != 200:
                    raise RuntimeError(f"Turso HTTP {response.status_code}")
                result = response.json()["results"][0]
                if result["type"] == "error":
                    raise RuntimeError(
                        "Turso SQL error: " + result["error"].get("code", "unknown")
                    )
                rows = result["response"]["result"]["rows"]
                return [
                    tuple(
                        int(value["value"])
                        if value["type"] == "integer"
                        else float(value["value"])
                        if value["type"] == "float"
                        else value.get("value")
                        for value in row
                    )
                    for row in rows
                ]
            except httpx.TransportError:
                if attempt == 3:
                    raise RuntimeError(
                        "Turso connection failed; rerun with --resume"
                    ) from None
                time.sleep(2**attempt)


def signature_sql(database, table: str) -> str:
    columns = [row[1] for row in database.execute(f'PRAGMA table_info("{table}")')]
    lengths = ",".join(f'COALESCE(SUM(length("{name}")),0)' for name in columns)
    return f'SELECT COUNT(*),SUM(rowid),MIN(rowid),MAX(rowid),{lengths} FROM "{table}"'


def upload(source: Path, remote: SqlHttp, resume: bool = False) -> None:
    started = time.monotonic()
    local = sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in remote.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        if tables:
            if not resume or not tables <= set(TABLES) or "metadata" not in tables:
                raise ValueError(
                    "Destination must be empty; --resume only accepts the same Moliner source"
                )
            query = "SELECT value FROM metadata WHERE key='source_sha256'"
            if remote.execute(query) != local.execute(query).fetchall():
                raise ValueError("Destination source fingerprint does not match")
        for table in TABLES:
            schema = local.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()[0]
            remote.execute(
                schema.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ", 1)
            )
        for table in TABLES:
            total = local.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            sent = 0
            report_at = time.monotonic()
            for sql, count in insert_batches(local, table):
                remote.execute(sql)
                sent += count
                if time.monotonic() - report_at >= 15:
                    print(f"{table}: {sent:,}/{total:,}", flush=True)
                    report_at = time.monotonic()
            query = signature_sql(local, table)
            if remote.execute(query) != local.execute(query).fetchall():
                raise ValueError(f"Verification failed for {table}")
            print(f"{table}: {total:,} rows uploaded and verified", flush=True)
        indexes = local.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name"
        ).fetchall()
        for (sql,) in indexes:
            remote.execute(
                sql.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
            )
        if remote.execute("PRAGMA foreign_key_check"):
            raise ValueError("Remote foreign key check failed")
        if remote.execute("PRAGMA integrity_check") != [("ok",)]:
            raise ValueError("Remote integrity check failed")
        print(
            f"Complete: {remote.requests} HTTP requests, {time.monotonic() - started:.1f}s; indexes and integrity verified",
            flush=True,
        )
    finally:
        local.close()
        remote.client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, default=ROOT / "site/data/moliner.sqlite"
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    url, token = (
        os.environ.get("MOLINER_DATABASE_URL"),
        os.environ.get("MOLINER_AUTH_TOKEN"),
    )
    if not url or not token:
        parser.error("Set MOLINER_DATABASE_URL and MOLINER_AUTH_TOKEN in .env")
    upload(args.database, SqlHttp(url, token), args.resume)
