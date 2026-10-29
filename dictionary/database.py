"""Adapt libSQL tuple results to the named rows used by the existing search."""

from __future__ import annotations

import os
from pathlib import Path

import libsql


class Rows:
    def __init__(self, cursor):
        self.cursor = cursor

    def row(self, values):
        if values is None:
            return None
        result = dict(enumerate(values))
        result.update(zip((column[0] for column in self.cursor.description), values))
        return result

    def fetchone(self):
        return self.row(self.cursor.fetchone())

    def fetchall(self):
        return [self.row(values) for values in self.cursor.fetchall()]


class LibsqlDatabase:
    def __init__(self, path: Path):
        url = os.environ.get("MOLINER_DATABASE_URL")
        if url:
            self.connection = libsql.connect(
                url, auth_token=os.environ.get("MOLINER_AUTH_TOKEN", "")
            )
        else:
            self.connection = libsql.connect(str(path))

    def execute(self, sql, parameters=()):
        return Rows(self.connection.execute(sql, parameters))

    def close(self):
        self.connection.close()
