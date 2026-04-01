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
        DROP TABLE IF EXISTS index_entries;
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

        CREATE TABLE index_entries (
            id INTEGER PRIMARY KEY,
            headword TEXT NOT NULL,
            normalized_headword TEXT NOT NULL,
            leo_offset INTEGER NOT NULL,
            page_span INTEGER NOT NULL,
            has_decoded_entry INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX idx_entries_normalized_headword
            ON entries(normalized_headword);
        CREATE INDEX idx_search_terms_normalized_term
            ON search_terms(normalized_term);
        CREATE INDEX idx_search_terms_entry
            ON search_terms(entry_id);
        CREATE INDEX idx_senses_entry_index
            ON senses(entry_id, sense_index);
        CREATE INDEX idx_index_entries_normalized_headword
            ON index_entries(normalized_headword);
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


def import_dictionary(
    json_path: Path, sqlite_path: Path, index_path: Path
) -> dict[str, int]:
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    entries = payload["entries"]
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    index_entries = index_payload["entries"]

    ensure_parent(sqlite_path)
    if sqlite_path.exists():
        sqlite_path.unlink()

    db = sqlite3.connect(sqlite_path)
    try:
        create_schema(db)

        entry_count = 0
        sense_count = 0
        search_term_count = 0
        index_entry_count = 0
        resolved_index_entry_count = 0
        resolved_exact_headwords: set[str] = set()

        with db:
            db.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("source_json", str(json_path)),
                    ("source_index_json", str(index_path)),
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
                resolved_exact_headwords.add(normalized_headword)

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

            seen_index_entries: set[tuple[str, int, int]] = set()
            for index_entry in index_entries:
                headword = str(index_entry["headword"]).strip()
                if not headword:
                    continue

                normalized_headword = normalize_for_search(headword)
                signature = (
                    normalized_headword,
                    int(index_entry["leo_offset"]),
                    int(index_entry["page_span"]),
                )
                if signature in seen_index_entries:
                    continue
                seen_index_entries.add(signature)

                has_decoded_entry = (
                    1 if normalized_headword in resolved_exact_headwords else 0
                )
                db.execute(
                    """
                    INSERT INTO index_entries(
                        headword,
                        normalized_headword,
                        leo_offset,
                        page_span,
                        has_decoded_entry
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        headword,
                        normalized_headword,
                        int(index_entry["leo_offset"]),
                        int(index_entry["page_span"]),
                        has_decoded_entry,
                    ),
                )
                index_entry_count += 1
                resolved_index_entry_count += has_decoded_entry

            db.executemany(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("index_entry_count", str(index_entry_count)),
                    ("resolved_index_entry_count", str(resolved_index_entry_count)),
                ],
            )
    finally:
        db.close()

    return {
        "entries": entry_count,
        "senses": sense_count,
        "search_terms": search_term_count,
        "index_entries": index_entry_count,
        "resolved_index_entries": resolved_index_entry_count,
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
        "--index",
        default="/home/tin/lab/UniLex/site/data/index.json",
        help="authentic IDO/LEO index JSON",
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
    stats = import_dictionary(Path(args.json), Path(args.sqlite), Path(args.index))
    print(
        f"imported {stats['entries']} entries,"
        f" {stats['senses']} senses and"
        f" {stats['search_terms']} search terms,"
        f" plus {stats['index_entries']} index entries"
        f" into {args.sqlite}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
