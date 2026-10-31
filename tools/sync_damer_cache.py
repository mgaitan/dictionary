"""Download the Turso DAMER cache to a local SQLite snapshot."""

import argparse
import os
import json
import sqlite3
import tempfile
from pathlib import Path

from dictionary.damer import SCHEMA, SNAPSHOT, decode_article, remote_sql


def sync(destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    remote_sql(SCHEMA)
    fd, temporary = tempfile.mkstemp(prefix=".damer-cache-", suffix=".sqlite", dir=destination.parent)
    os.close(fd)
    count = 0
    try:
        with sqlite3.connect(temporary) as db:
            db.execute(SCHEMA)
            cursor = ""
            while True:
                rows = remote_sql("SELECT word, article FROM damer_articles WHERE word > ? ORDER BY word LIMIT 500", (cursor,))
                if not rows:
                    break
                db.executemany("INSERT INTO damer_articles VALUES (?, ?)", ((word, json.dumps(decode_article(article), ensure_ascii=False)) for word, article in rows))
                count += len(rows)
                cursor = rows[-1][0]
            db.commit()
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("La copia SQLite no pasó la verificación de integridad")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=SNAPSHOT)
    args = parser.parse_args()
    print(f"Copia local actualizada: {sync(args.sqlite)} artículos")
