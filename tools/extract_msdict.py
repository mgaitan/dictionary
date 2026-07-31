#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///

"""Inspect and extract dictionaries stored in the MSDict Palm PDB format.

MSDict article records use a non-obvious branched raw-DEFLATE representation:
many articles share a compressed prefix, while an index descriptor selects a
bit-aligned continuation by ``(record, offset)``. The record header stores the
bit shift in its three high bits. Metadata, index block declarations, and
decompressed article markup use a compact BER encoding.

This dependency-free tool implements the complete path from Palm record table
to a FastAPI-compatible SQLite database. Without ``--sqlite`` it prints
metadata, index blocks, and decoded samples as JSON, which is useful when
examining related MSDict databases.

Examples:
    uv run tools/extract_msdict.py EnglishSpanish.pdb --samples 5
    uv run tools/extract_msdict.py EnglishSpanish.pdb \
        --sqlite site/data/en-es-dictionary.sqlite
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import struct
import sys
import unicodedata
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path


class MSDictError(ValueError):
    """Raised when an MSDict structure is malformed or unsupported."""


@dataclass(frozen=True)
class BerNode:
    tag_class: int
    tag: int
    constructed: bool
    value: bytes
    children: tuple[BerNode, ...]

    def find_children(self, tag: int) -> Iterator[BerNode]:
        return (
            child
            for child in self.children
            if child.tag_class == 1 and child.tag == tag
        )

    def first_child(self, tag: int) -> BerNode | None:
        return next(self.find_children(tag), None)


@dataclass(frozen=True)
class IndexBlock:
    record: int
    count: int
    boundary: bytes


@dataclass(frozen=True)
class Metadata:
    title: str
    encoding: str
    publisher: str
    source_language: str
    primary_index: tuple[IndexBlock, ...]
    article_index: tuple[IndexBlock, ...]
    primary_sort_record: int
    article_sort_record: int
    stylesheet_record: int

    @property
    def entry_count(self) -> int:
        return sum(block.count for block in self.primary_index)


class PalmDatabase:
    """Read record slices from a classic Palm database container."""
    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        if len(self.data) < 78:
            raise MSDictError(f"{path} is too short to be a Palm database")

        record_count = struct.unpack_from(">H", self.data, 76)[0]
        table_end = 78 + record_count * 8
        if table_end > len(self.data):
            raise MSDictError(f"{path} has a truncated Palm record table")

        offsets = [
            struct.unpack_from(">I", self.data, 78 + index * 8)[0]
            for index in range(record_count)
        ]
        if offsets != sorted(offsets) or any(
            offset < table_end or offset >= len(self.data) for offset in offsets
        ):
            raise MSDictError(f"{path} has invalid Palm record offsets")

        self._offsets = offsets

    def __len__(self) -> int:
        return len(self._offsets)

    def record(self, index: int) -> bytes:
        start = self._offsets[index]
        end = self._offsets[index + 1] if index + 1 < len(self) else len(self.data)
        return self.data[start:end]


def _read_base128(data: bytes, position: int, end: int) -> tuple[int, int]:
    value = 0
    while position < end:
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, position
    raise MSDictError("truncated base-128 integer")


def _parse_ber_node(data: bytes, position: int, end: int) -> tuple[BerNode, int]:
    if position >= end:
        raise MSDictError("missing BER tag")

    first = data[position]
    position += 1
    tag = first & 0x1F
    if tag == 0x1F:
        tag, position = _read_base128(data, position, end)

    length, position = _read_base128(data, position, end)
    value_end = position + length
    if value_end > end:
        raise MSDictError(
            f"BER value extends {value_end - end} bytes past its container"
        )

    constructed = bool(first & 0x20)
    children: list[BerNode] = []
    if constructed:
        child_position = position
        while child_position < value_end:
            child, child_position = _parse_ber_node(data, child_position, value_end)
            children.append(child)
        value = b""
    else:
        value = data[position:value_end]

    return (
        BerNode(
            tag_class=(first >> 6) & 0x03,
            tag=tag,
            constructed=constructed,
            value=value,
            children=tuple(children),
        ),
        value_end,
    )


def parse_ber(data: bytes) -> BerNode:
    """Parse one complete definite-length BER value used by MSDict."""
    node, position = _parse_ber_node(data, 0, len(data))
    if position != len(data):
        raise MSDictError(f"{len(data) - position} trailing bytes after BER root")
    return node


def _integer(node: BerNode | None, default: int = 0) -> int:
    if node is None:
        return default
    if len(node.value) > 2:
        raise MSDictError(f"unexpected {len(node.value)}-byte MSDict integer")
    return int.from_bytes(node.value, "big")


def _text(node: BerNode | None, encoding: str = "ascii") -> str:
    return "" if node is None else node.value.decode(encoding)


def _parse_blocks(node: BerNode | None) -> tuple[IndexBlock, ...]:
    if node is None:
        return ()

    declared_count = _integer(node.first_child(8))
    blocks: list[IndexBlock] = []
    for child in node.find_children(9):
        blocks.append(
            IndexBlock(
                record=_integer(child.first_child(10)),
                count=_integer(child.first_child(11)),
                boundary=(child.first_child(12) or BerNode(0, 0, False, b"", ())).value,
            )
        )
    if declared_count != len(blocks):
        raise MSDictError(
            f"metadata declares {declared_count} index blocks, found {len(blocks)}"
        )
    return tuple(blocks)


def parse_metadata(record: bytes) -> Metadata:
    """Decode MSDict record zero and its primary/article index block maps."""
    root = parse_ber(record)
    if root.tag_class != 1 or root.tag != 0 or not root.constructed:
        raise MSDictError("record 0 is not an MSDict metadata root")

    encoding = _text(root.first_child(15)) or "Cp1252"
    return Metadata(
        title=_text(root.first_child(1), "utf-8"),
        encoding=encoding,
        publisher=_text(root.first_child(18)),
        source_language=_text(root.first_child(19)),
        primary_index=_parse_blocks(root.first_child(7)),
        article_index=_parse_blocks(root.first_child(22)),
        primary_sort_record=_integer(root.first_child(13)),
        article_sort_record=_integer(root.first_child(23), 0xFFFF),
        stylesheet_record=_integer(root.first_child(14)),
    )


def _locate_block(
    blocks: tuple[IndexBlock, ...], entry_index: int
) -> tuple[IndexBlock, int]:
    if entry_index < 0:
        raise IndexError(entry_index)
    local_index = entry_index
    for block in blocks:
        if local_index < block.count:
            return block, local_index
        local_index -= block.count
    raise IndexError(entry_index)


def read_index_descriptor(record: bytes, local_index: int) -> tuple[int, int, bytes]:
    """Return the two pointer fields and payload of a six-byte index descriptor."""
    if len(record) < 2:
        raise MSDictError("truncated index record")
    count = int.from_bytes(record[:2], "big")
    if local_index < 0 or local_index >= count:
        raise IndexError(local_index)

    descriptors_end = 2 + count * 6
    descriptor = 2 + local_index * 6
    if descriptors_end > len(record):
        raise MSDictError("truncated index descriptor table")

    first = int.from_bytes(record[descriptor : descriptor + 2], "big")
    second = int.from_bytes(record[descriptor + 2 : descriptor + 4], "big")
    data_start = descriptors_end + int.from_bytes(
        record[descriptor + 4 : descriptor + 6], "big"
    )
    if local_index + 1 < count:
        next_descriptor = descriptor + 6
        data_end = descriptors_end + int.from_bytes(
            record[next_descriptor + 4 : next_descriptor + 6], "big"
        )
    else:
        data_end = len(record)
    if not descriptors_end <= data_start <= data_end <= len(record):
        raise MSDictError("invalid index payload offsets")
    return first, second, record[data_start:data_end]


def _split_index_payload(payload: bytes) -> tuple[bytes, bytes]:
    if len(payload) <= 1 or payload[0] != 0:
        return payload, payload
    alternate_length = payload[1]
    alternate_end = 2 + alternate_length
    if alternate_end > len(payload):
        raise MSDictError("truncated alternate index spelling")
    return payload[2:alternate_end], payload[alternate_end:]


def decode_article(record: bytes, branch_offset: int) -> bytes:
    """Inflate one article continuation from a shared, bit-aligned DEFLATE record."""
    if len(record) < 4:
        raise MSDictError("truncated compressed article record")
    if branch_offset < 4 or branch_offset >= len(record):
        raise MSDictError(f"article branch offset {branch_offset} is outside record")

    shift = record[0] >> 5
    prefix_length = int.from_bytes(record[1:3], "big")
    prefix_end = 3 + prefix_length
    if prefix_length == 0 or prefix_end > len(record):
        raise MSDictError("invalid compressed article prefix")

    compressed_prefix = bytearray(record[3:prefix_end])
    mask = (1 << shift) - 1
    if shift:
        compressed_prefix[-1] |= (record[branch_offset] & mask) << (8 - shift)

    inflater = zlib.decompressobj(wbits=-15)
    output = bytearray(inflater.decompress(compressed_prefix))
    position = branch_offset
    while not inflater.eof:
        if position >= len(record):
            raise MSDictError("compressed article did not reach end-of-stream")
        chunk_end = min(position + 64, len(record))
        chunk = bytearray(chunk_end - position)
        for output_index, input_index in enumerate(range(position, chunk_end)):
            shifted = record[input_index] >> shift
            if shift and input_index + 1 < len(record):
                shifted |= (record[input_index + 1] & mask) << (8 - shift)
            chunk[output_index] = shifted
        output.extend(inflater.decompress(chunk))
        position = chunk_end
    output.extend(inflater.flush())
    return bytes(output)


ARTICLE_ELEMENT_TYPES = {
    1: 0,  # body
    2: 2,  # p
    3: 3,  # span
    4: 7,  # a
    5: 4,  # table
    6: 5,  # tr
    7: 6,  # td
    8: 8,  # ul
    9: 9,  # li
    10: 10,  # br
    13: 12,  # div
    14: 13,  # img
}
BLOCK_ELEMENT_TYPES = {0, 2, 4, 5, 6, 8, 9, 10, 12, 14, 15, 16, 17, 18, 19}


def article_text_lines(article: bytes, encoding: str) -> list[str]:
    """Render visible BER text nodes into stable block-oriented plain-text lines."""
    root = parse_ber(article)
    tokens: list[str] = []

    def visit(node: BerNode) -> None:
        element_type = (
            ARTICLE_ELEMENT_TYPES.get(node.tag)
            if node.tag_class == 1 and node.constructed
            else None
        )
        if element_type in BLOCK_ELEMENT_TYPES:
            tokens.append("\n")

        if node.constructed:
            for child in node.children:
                visit(child)
        elif node.tag_class != 1 and node.value:
            tokens.append(node.value.decode(encoding))

        if element_type in BLOCK_ELEMENT_TYPES:
            tokens.append("\n")

    visit(root)
    text = "".join(tokens).replace("\xa0", " ")
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return lines


class MSDict:
    def __init__(self, path: Path):
        self.database = PalmDatabase(path)
        self.metadata = parse_metadata(self.database.record(0))

    def __len__(self) -> int:
        return self.metadata.entry_count

    def _index_value(
        self, blocks: tuple[IndexBlock, ...], entry_index: int
    ) -> tuple[int, int, bytes]:
        block, local_index = _locate_block(blocks, entry_index)
        return read_index_descriptor(self.database.record(block.record), local_index)

    def headword(self, entry_index: int) -> str:
        _first, _second, payload = self._index_value(
            self.metadata.primary_index, entry_index
        )
        alternate, _primary = _split_index_payload(payload)
        return alternate.decode(self.metadata.encoding)

    def primary_headword(self, entry_index: int) -> str:
        _first, _second, payload = self._index_value(
            self.metadata.primary_index, entry_index
        )
        _alternate, primary = _split_index_payload(payload)
        return primary.decode(self.metadata.encoding)

    def article_location(self, entry_index: int) -> tuple[int, int]:
        blocks = self.metadata.article_index or self.metadata.primary_index
        record, offset, _payload = self._index_value(blocks, entry_index)
        return record, offset

    def article(self, entry_index: int) -> bytes:
        record, offset = self.article_location(entry_index)
        return decode_article(self.database.record(record), offset)


def normalize_for_search(value: str) -> str:
    folded = value.strip().replace("ß", "ss").replace("ẞ", "ss").replace("·", "")
    decomposed = unicodedata.normalize("NFD", folded)
    ascii_text = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text.lower())
    return re.sub(r"\s+", " ", ascii_text).strip()


def clean_display_headword(article_headword: str, index_headword: str) -> str:
    cleaned = re.sub(
        r"\s*\[(?:Verb Table|Vocabulary notes|Grammar notes)[^\]]*\]",
        "",
        article_headword,
        flags=re.IGNORECASE,
    ).strip()
    article_match = re.fullmatch(r"(.+?)(\d+)", cleaned)
    index_match = re.fullmatch(r"(.+?)\((\d+)\)", index_headword)
    if (
        article_match
        and index_match
        and article_match.group(1).casefold() == index_match.group(1).casefold()
        and article_match.group(2) == index_match.group(2)
    ):
        return article_match.group(1).strip()
    return cleaned


def create_site_schema(database: sqlite3.Connection) -> None:
    """Create the same SQLite interface used by the UniLex import pipeline."""
    database.executescript(
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


def build_site_database(pdb_path: Path, sqlite_path: Path) -> dict[str, int]:
    """Decode an MSDict PDB and write a complete site-compatible SQLite file."""
    dictionary = MSDict(pdb_path)
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    sqlite_path.unlink(missing_ok=True)

    database = sqlite3.connect(sqlite_path)
    grouped_entries: dict[str, int] = {}
    search_terms: dict[int, set[str]] = {}
    senses_per_entry: dict[int, int] = {}
    sense_count = 0

    try:
        create_site_schema(database)
        with database:
            database.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("format", "MSDict PDB branched-DEFLATE"),
                    ("source_pdb", pdb_path.name),
                    ("title", dictionary.metadata.title),
                    ("publisher", dictionary.metadata.publisher),
                    ("source_language", dictionary.metadata.source_language),
                    ("encoding", dictionary.metadata.encoding),
                ],
            )

            for entry_index in range(len(dictionary)):
                location = dictionary.article_location(entry_index)
                primary_headword = dictionary.primary_headword(entry_index).strip()
                article = decode_article(
                    dictionary.database.record(location[0]), location[1]
                )
                lines = article_text_lines(article, dictionary.metadata.encoding)
                article_headword = (lines[0] if lines else primary_headword).strip()
                headword = clean_display_headword(
                    article_headword, primary_headword
                ).strip()
                if not headword:
                    raise MSDictError(f"entry {entry_index} has no headword")
                glosses = lines[1:] if len(lines) > 1 else lines
                entry_id = grouped_entries.get(headword)

                if entry_id is None:
                    cursor = database.execute(
                        """
                        INSERT INTO entries(
                            headword, normalized_headword, decoded_complete
                        )
                        VALUES (?, ?, 1)
                        """,
                        (headword, normalize_for_search(headword)),
                    )
                    entry_id = int(cursor.lastrowid)
                    grouped_entries[headword] = entry_id
                    search_terms[entry_id] = set()
                    senses_per_entry[entry_id] = 0
                    _insert_search_term(
                        database, search_terms, entry_id, headword, "headword"
                    )

                database.execute(
                    """
                    INSERT INTO senses(
                        entry_id, sense_index, source, glosses_json, tags_json
                    )
                    VALUES (?, ?, '', ?, '[]')
                    """,
                    (
                        entry_id,
                        senses_per_entry[entry_id],
                        json.dumps(glosses, ensure_ascii=False),
                    ),
                )
                senses_per_entry[entry_id] += 1
                sense_count += 1
                _insert_search_term(
                    database, search_terms, entry_id, primary_headword, "variant"
                )
                _insert_search_term(
                    database, search_terms, entry_id, article_headword, "variant"
                )
                database.execute(
                    """
                    INSERT INTO index_entries(
                        headword, normalized_headword, leo_offset, page_span,
                        has_decoded_entry
                    )
                    VALUES (?, ?, ?, 1, 1)
                    """,
                    (
                        primary_headword,
                        normalize_for_search(primary_headword),
                        entry_index,
                    ),
                )

                if entry_index and entry_index % 5000 == 0:
                    print(
                        f"decoded {entry_index:,}/{len(dictionary):,} index entries",
                        file=sys.stderr,
                    )

            database.executemany(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                [
                    ("entry_count", str(len(grouped_entries))),
                    ("sense_count", str(sense_count)),
                    (
                        "search_term_count",
                        str(sum(len(terms) for terms in search_terms.values())),
                    ),
                    ("index_entry_count", str(len(dictionary))),
                    ("resolved_index_entry_count", str(len(dictionary))),
                ],
            )
    except Exception:
        database.close()
        sqlite_path.unlink(missing_ok=True)
        raise
    else:
        database.close()

    return {
        "entries": len(grouped_entries),
        "senses": sense_count,
        "search_terms": sum(len(terms) for terms in search_terms.values()),
        "index_entries": len(dictionary),
        "resolved_index_entries": len(dictionary),
    }


def _insert_search_term(
    database: sqlite3.Connection,
    seen: dict[int, set[str]],
    entry_id: int,
    term: str,
    kind: str,
) -> None:
    normalized = normalize_for_search(term)
    if not normalized or normalized in seen[entry_id]:
        return
    seen[entry_id].add(normalized)
    database.execute(
        """
        INSERT INTO search_terms(entry_id, term, normalized_term, kind)
        VALUES (?, ?, ?, ?)
        """,
        (entry_id, term, normalized, kind),
    )


def inspect_dictionary(path: Path, sample_count: int) -> dict[str, object]:
    dictionary = MSDict(path)
    metadata = dictionary.metadata
    metadata_root = parse_ber(dictionary.database.record(0))
    samples = []
    for entry_index in range(min(sample_count, len(dictionary))):
        record, offset = dictionary.article_location(entry_index)
        article = dictionary.article(entry_index)
        samples.append(
            {
                "index": entry_index,
                "headword": dictionary.headword(entry_index),
                "primary_headword": dictionary.primary_headword(entry_index),
                "article_record": record,
                "article_offset": offset,
                "article_bytes": len(article),
                "text_lines": article_text_lines(article, metadata.encoding),
                "article_preview": article[:160].decode(
                    metadata.encoding, errors="replace"
                ),
            }
        )
    return {
        "path": str(path),
        "palm_records": len(dictionary.database),
        "title": metadata.title,
        "encoding": metadata.encoding,
        "publisher": metadata.publisher,
        "source_language": metadata.source_language,
        "entry_count": len(dictionary),
        "primary_sort_record": metadata.primary_sort_record,
        "article_sort_record": metadata.article_sort_record,
        "stylesheet_record": metadata.stylesheet_record,
        "metadata_children": [
            {
                "class": child.tag_class,
                "tag": child.tag,
                "constructed": child.constructed,
                "length": (
                    len(child.value) if not child.constructed else len(child.children)
                ),
            }
            for child in metadata_root.children
        ],
        "primary_index_blocks": [
            {
                "record": block.record,
                "count": block.count,
                "boundary": block.boundary.decode(metadata.encoding, errors="replace"),
            }
            for block in metadata.primary_index
        ],
        "article_index_blocks": [
            {
                "record": block.record,
                "count": block.count,
                "boundary_hex": block.boundary.hex(),
            }
            for block in metadata.article_index
        ],
        "samples": samples,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdb", type=Path, help="MSDict Palm database")
    parser.add_argument(
        "--samples",
        type=int,
        default=5,
        help="number of entries to decode in inspection output",
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        help="decode the full PDB into a site-compatible SQLite database",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.sqlite:
            stats = build_site_database(args.pdb, args.sqlite)
            print(
                f"imported {stats['entries']:,} entries, {stats['senses']:,} senses,"
                f" {stats['search_terms']:,} search terms and"
                f" {stats['index_entries']:,} index rows into {args.sqlite}"
            )
            return 0
        payload = inspect_dictionary(args.pdb, args.samples)
    except (MSDictError, OSError, UnicodeError, zlib.error) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
