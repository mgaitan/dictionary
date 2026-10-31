"""Build a small index of full gender forms for the existing Moliner database."""

import os
import sqlite3
from pathlib import Path

from dictionary.moliner import gender_variants
from dictionary.search import DATA_DIR, normalize_for_search


def build(source: Path, destination: Path) -> int:
    temporary = destination.with_suffix(".sqlite.tmp")
    temporary.unlink(missing_ok=True)
    count = 0
    try:
        with sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True) as original, sqlite3.connect(temporary) as db:
            db.executescript("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL); CREATE TABLE search_terms (entry_id INTEGER NOT NULL, term TEXT NOT NULL, normalized_term TEXT NOT NULL, kind TEXT NOT NULL); CREATE INDEX idx_variants_normalized ON search_terms(normalized_term);")
            fingerprint = original.execute("SELECT value FROM metadata WHERE key = 'source_sha256'").fetchone()
            if not fingerprint:
                raise ValueError("La base de Moliner no tiene identificación del origen")
            db.execute("INSERT INTO metadata VALUES ('source_sha256', ?)", fingerprint)
            for entry_id, headword in original.execute("SELECT id, headword FROM entries"):
                variants = gender_variants(headword)
                db.executemany("INSERT INTO search_terms VALUES (?, ?, ?, 'variant')", ((entry_id, term, normalize_for_search(term)) for term in variants))
                count += len(variants)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return count


if __name__ == "__main__":
    print(f"{build(DATA_DIR / 'moliner.sqlite', DATA_DIR / 'moliner-variants.sqlite')} variantes indexadas")
