#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///

from __future__ import annotations

import argparse
import json
import sqlite3
import unicodedata
from pathlib import Path


def normalize_for_search(value: str) -> str:
    text = unicodedata.normalize("NFD", value)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text.casefold().strip()


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def create_schema(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;
        PRAGMA temp_store = MEMORY;

        DROP TABLE IF EXISTS metadata;
        DROP TABLE IF EXISTS search_terms;
        DROP TABLE IF EXISTS senses;
        DROP TABLE IF EXISTS entries;

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE entries (
            id INTEGER PRIMARY KEY,
            headword TEXT NOT NULL,
            normalized_headword TEXT NOT NULL,
            decoded_complete INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE senses (
            id INTEGER PRIMARY KEY,
            entry_id INTEGER NOT NULL,
            sense_index INTEGER NOT NULL,
            source TEXT NOT NULL,
            glosses_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
        );

        CREATE TABLE search_terms (
            entry_id INTEGER NOT NULL,
            term TEXT NOT NULL,
            normalized_term TEXT NOT NULL,
            kind TEXT NOT NULL,
            FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
        );

        CREATE INDEX idx_entries_normalized_headword
            ON entries(normalized_headword);
        CREATE INDEX idx_search_terms_normalized_term
            ON search_terms(normalized_term);
        CREATE INDEX idx_search_terms_entry
            ON search_terms(entry_id);
        CREATE INDEX idx_senses_entry_index
            ON senses(entry_id, sense_index);
        """
    )


def iter_search_terms(entry: dict[str, object]) -> list[tuple[str, str]]:
    terms: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for kind, values in (
        ("headword", [entry["headword"]]),
        ("variant", entry.get("variants", [])),
    ):
        for value in values:
            term = str(value).strip()
            if not term:
                continue
            normalized = normalize_for_search(term)
            if not normalized:
                continue
            key = (kind, normalized)
            if key in seen:
                continue
            seen.add(key)
            terms.append((kind, term))

    return terms


def import_dictionary(json_path: Path, sqlite_path: Path) -> dict[str, int]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    entries = payload["entries"]

    ensure_parent(sqlite_path)
    if sqlite_path.exists():
        sqlite_path.unlink()

    db = sqlite3.connect(sqlite_path)
    try:
        create_schema(db)

        entry_count = 0
        sense_count = 0
        search_term_count = 0

        with db:
            db.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("source_json", str(json_path)),
                    ("entry_count", str(len(entries))),
                ],
            )

            for entry in entries:
                headword = str(entry["headword"]).strip()
                normalized_headword = normalize_for_search(headword)
                decoded_complete = 1 if entry.get("decodedComplete") else 0

                cursor = db.execute(
                    """
                    INSERT INTO entries(headword, normalized_headword, decoded_complete)
                    VALUES (?, ?, ?)
                    """,
                    (headword, normalized_headword, decoded_complete),
                )
                entry_id = int(cursor.lastrowid)
                entry_count += 1

                for sense_index, sense in enumerate(entry.get("senses", [])):
                    db.execute(
                        """
                        INSERT INTO senses(entry_id, sense_index, source, glosses_json, tags_json)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            entry_id,
                            sense_index,
                            str(sense.get("source") or "").strip(),
                            json.dumps(sense.get("glosses") or [], ensure_ascii=False),
                            json.dumps(sense.get("tags") or [], ensure_ascii=False),
                        ),
                    )
                    sense_count += 1

                for kind, term in iter_search_terms(entry):
                    db.execute(
                        """
                        INSERT INTO search_terms(entry_id, term, normalized_term, kind)
                        VALUES (?, ?, ?, ?)
                        """,
                        (entry_id, term, normalize_for_search(term), kind),
                    )
                    search_term_count += 1

            db.executemany(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("sense_count", str(sense_count)),
                    ("search_term_count", str(search_term_count)),
                ],
            )
    finally:
        db.close()

    return {
        "entries": entry_count,
        "senses": sense_count,
        "search_terms": search_term_count,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build SQLite database for the PHP site"
    )
    parser.add_argument(
        "--json",
        default="/home/tin/lab/UniLex/site/data/dictionary-indexed.json",
        help="clean dictionary JSON generated for the site",
    )
    parser.add_argument(
        "--sqlite",
        default="/home/tin/lab/UniLex/site/data/dictionary.sqlite",
        help="output SQLite file",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    stats = import_dictionary(Path(args.json), Path(args.sqlite))
    print(
        f"imported {stats['entries']} entries,"
        f" {stats['senses']} senses and"
        f" {stats['search_terms']} search terms"
        f" into {args.sqlite}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
