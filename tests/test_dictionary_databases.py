from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from dictionary.search import DICTIONARIES

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
DATABASES = {
    "de-es": "de-es-dictionary.sqlite",
    "es-de": "es-de-dictionary.sqlite",
    "en-es": "en-es-dictionary.sqlite",
    "es-en": "es-en-dictionary.sqlite",
}
TABLES = ("metadata", "entries", "senses", "search_terms", "index_entries")
COUNT_METADATA = {
    "entry_count",
    "sense_count",
    "search_term_count",
    "index_entry_count",
    "resolved_index_entry_count",
}


def table_contract(database: sqlite3.Connection) -> dict[str, list[tuple[str, str]]]:
    return {
        table: [
            (str(row[1]), str(row[2]))
            for row in database.execute(f"PRAGMA table_info({table})")
        ]
        for table in TABLES
    }


def test_all_dictionary_directions_share_database_contract() -> None:
    reference_path = DATA_DIR / DATABASES["de-es"]
    with closing(sqlite3.connect(reference_path)) as reference:
        expected_contract = table_contract(reference)

    for dictionary_id, filename in DATABASES.items():
        path = DATA_DIR / filename
        assert path.is_file()
        assert DICTIONARIES[dictionary_id].database_path == path

        with closing(sqlite3.connect(path)) as database:
            assert table_contract(database) == expected_contract
            metadata = dict(database.execute("SELECT key, value FROM metadata"))

        assert COUNT_METADATA <= metadata.keys()
        assert not any("/home/" in value for value in metadata.values())
