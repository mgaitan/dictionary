import sqlite3

import httpx
import pytest

from tools.upload_moliner import SqlHttp, insert_batches, signature_sql


@pytest.mark.parametrize("primary_key", [True, False])
def test_bulk_batches_preserve_data_rowids_and_allow_retries(primary_key):
    source = sqlite3.connect(":memory:")
    target = sqlite3.connect(":memory:")
    schema = (
        "CREATE TABLE entries (id INTEGER"
        + (" PRIMARY KEY" if primary_key else "")
        + ", text TEXT, blob BLOB)"
    )
    source.execute(schema)
    target.execute(schema)
    source.executemany(
        "INSERT INTO entries(rowid,id,text,blob) VALUES (?,?,?,?)",
        [
            (3, 3, "María's *definición* <FUENTE>ñ</FUENTE>", b"\x00\xff"),
            (9, 9, None, None),
            (20, 20, "casa\nábaco\u00a0café", b""),
        ],
    )
    batches = list(insert_batches(source, "entries", max_bytes=140))
    assert len(batches) > 1 and sum(count for _, count in batches) == 3
    for _ in range(2):
        for sql, _ in batches:
            target.execute(sql)
    assert (
        source.execute("SELECT rowid,* FROM entries").fetchall()
        == target.execute("SELECT rowid,* FROM entries").fetchall()
    )
    sql = signature_sql(source, "entries")
    assert source.execute(sql).fetchall() == target.execute(sql).fetchall()


def test_http_sql_errors_inside_successful_response_are_detected():
    remote = SqlHttp("libsql://example.invalid", "test-token")
    remote.client.close()
    remote.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"results": [{"type": "error", "error": {"code": "SQLITE_FULL"}}]},
            )
        )
    )
    try:
        with pytest.raises(RuntimeError, match="SQLITE_FULL"):
            remote.execute("SELECT 1")
    finally:
        remote.client.close()
