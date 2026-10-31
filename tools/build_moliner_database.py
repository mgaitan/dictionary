"""Build the independent Moliner SQLite database from the lossless XML export."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import sqlite3

from dictionary.moliner import gender_variants, plain_text
from dictionary.search import normalize_for_search

ROOT = Path(__file__).resolve().parent.parent


def search_terms(root: ET.Element, headword: str) -> list[tuple[str, str]]:
    lemma = root.find("./VOZ/LEMA")
    if lemma is None:
        raise ValueError("DUE article has no lemma")
    base = "".join(
        [lemma.text or ""]
        + [
            ("" if child.get("sup") == "1" else plain_text(child)) + (child.tail or "")
            for child in lemma
        ]
    ).strip()
    terms = {(headword, "headword"), (base, "variant")}
    terms.update((term, "variant") for term in gender_variants(base))
    for node in root.iter():
        if node.tag in {"LEXIA", "VARIANTE-LEMA", "LEMA-2"}:
            term = plain_text(node)
            terms.add((term, "variant"))
            if base and node.tag == "LEXIA":
                expanded = re.sub(
                    rf"\b{re.escape(base[0])}\.",
                    lambda _: base,
                    term,
                    flags=re.IGNORECASE,
                )
                terms.add((expanded, "variant"))
    return sorted((term, kind) for term, kind in terms if normalize_for_search(term))


def build_database(source: Path, output: Path) -> dict[str, int]:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    db = sqlite3.connect(str(temporary))
    counts = {"entries": 0, "senses": 0, "search_terms": 0, "xml_ids": 0}
    try:
        db.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE entries (
                id INTEGER PRIMARY KEY, headword TEXT NOT NULL,
                normalized_headword TEXT NOT NULL, decoded_complete INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE senses (
                id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries(id),
                sense_index INTEGER NOT NULL, source TEXT NOT NULL,
                glosses_json TEXT NOT NULL, tags_json TEXT NOT NULL
            );
            CREATE TABLE search_terms (
                entry_id INTEGER NOT NULL REFERENCES entries(id), term TEXT NOT NULL,
                normalized_term TEXT NOT NULL, kind TEXT NOT NULL
            );
            CREATE TABLE articles (
                entry_id INTEGER PRIMARY KEY REFERENCES entries(id), entry_xml TEXT NOT NULL
            );
            CREATE TABLE xml_ids (
                xml_id TEXT PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries(id)
            );
        """)
        with source.open(encoding="utf-8") as stream:
            for line in stream:
                article = json.loads(line)
                root = ET.fromstring(article["entry_xml"])
                entry_id = int(article["id"])
                if root.tag != "ENTRADA" or root.get("id-entrada") != str(entry_id):
                    raise ValueError(f"Inconsistent article ID: {entry_id}")
                headword = article["headword"]
                terms = search_terms(root, headword)
                senses = list(root.iter("ACEPCION"))
                db.execute(
                    "INSERT INTO entries VALUES (?, ?, ?, 1)",
                    (entry_id, headword, normalize_for_search(headword)),
                )
                db.execute(
                    "INSERT INTO articles VALUES (?, ?)",
                    (entry_id, article["entry_xml"]),
                )
                db.executemany(
                    "INSERT INTO senses(entry_id, sense_index, source, glosses_json, tags_json) VALUES (?, ?, '', ?, '[]')",
                    [
                        (
                            entry_id,
                            i,
                            json.dumps([plain_text(sense)], ensure_ascii=False),
                        )
                        for i, sense in enumerate(senses)
                    ],
                )
                db.executemany(
                    "INSERT INTO search_terms VALUES (?, ?, ?, ?)",
                    [
                        (entry_id, term, normalize_for_search(term), kind)
                        for term, kind in terms
                    ],
                )
                ids = [
                    (node.get("id"), entry_id) for node in root.iter() if node.get("id")
                ]
                db.executemany("INSERT INTO xml_ids VALUES (?, ?)", ids)
                counts["entries"] += 1
                counts["senses"] += len(senses)
                counts["search_terms"] += len(terms)
                counts["xml_ids"] += len(ids)
        if not counts["entries"]:
            raise ValueError("The article export is empty")
        db.executescript("""
            CREATE INDEX idx_entries_normalized_headword ON entries(normalized_headword);
            CREATE INDEX idx_search_terms_normalized_term ON search_terms(normalized_term);
            CREATE INDEX idx_search_terms_entry ON search_terms(entry_id);
            CREATE INDEX idx_senses_entry_index ON senses(entry_id, sense_index);
        """)
        with source.open("rb") as stream:
            source_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        db.executemany(
            "INSERT INTO metadata VALUES (?, ?)",
            [
                ("title", "Diccionario de uso del español — María Moliner"),
                ("edition", "DUE 3.0 / 3.ª edición"),
                ("source", "Setup/index/lemas/_7jy.cfs: original stored XML"),
                ("source_sha256", source_digest),
                *[(key + "_count", str(value)) for key, value in counts.items()],
            ],
        )
        db.commit()
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Database integrity check failed")
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError("Database foreign key check failed")
    except BaseException:
        db.close()
        temporary.unlink(missing_ok=True)
        raise
    else:
        db.close()
        temporary.replace(output)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=ROOT / "site/data/moliner-articles.jsonl"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "site/data/moliner.sqlite"
    )
    args = parser.parse_args()
    print(build_database(args.source, args.output))
