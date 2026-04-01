#!/usr/bin/env -S uv run
# /// script
# dependencies = ["pefile"]
# ///

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pefile

from analyze_slagro import DEFAULT_RECORD_TYPE, build_index
from inspect_unilex import ROOT, read_page

DEFAULT_DLL = Path('/home/tin/lab/UniLex/UniLex - Brandstetter Slaby/program/aclexman.dll')
DEFAULT_OUTPUT = Path('/home/tin/lab/UniLex/site/data/dictionary.json')
DEFAULT_CODEBOOK_RVA = 0x10042050
CODEBOOK_ENTRY_COUNT = 256
CODEBOOK_ENTRY_SIZE = 5


def normalize_headword(value: str) -> str:
    normalized = value.casefold().replace('·', '')
    return re.sub(r'[^\w]+', '', normalized)


def build_decoder_table(dll_path: Path, codebook_rva: int) -> list[tuple[int, int]]:
    pe = pefile.PE(str(dll_path))
    blob = pe.get_data(codebook_rva - pe.OPTIONAL_HEADER.ImageBase, CODEBOOK_ENTRY_COUNT * CODEBOOK_ENTRY_SIZE)
    if len(blob) != CODEBOOK_ENTRY_COUNT * CODEBOOK_ENTRY_SIZE:
        raise ValueError(f'short codebook at RVA 0x{codebook_rva:x}')

    return [
        (
            int.from_bytes(blob[index * CODEBOOK_ENTRY_SIZE : index * CODEBOOK_ENTRY_SIZE + 4], 'little'),
            blob[index * CODEBOOK_ENTRY_SIZE + 4],
        )
        for index in range(CODEBOOK_ENTRY_COUNT)
    ]


def build_decoder_tree(table: list[tuple[int, int]]) -> list[list[int]]:
    nodes: list[list[int]] = [[-1, -1, -1] for _ in range(4096)]
    next_index = 1

    for symbol, (code, bit_count) in enumerate(table):
        if bit_count == 0:
            continue

        cursor = 0
        for bit_index in range(bit_count - 1, -1, -1):
            bit = (code >> bit_index) & 1
            child = nodes[cursor][bit]
            if child == -1:
                child = next_index
                next_index += 1
                if next_index >= len(nodes):
                    nodes.extend([[-1, -1, -1] for _ in range(2048)])
                nodes[cursor][bit] = child
            cursor = child
        nodes[cursor][2] = symbol

    return nodes


def decode_payload(tree: list[list[int]], payload: bytes, *, limit: int = 20000) -> tuple[bytes, bool]:
    out: list[int] = []
    cursor = 0

    for byte in payload:
        for shift in range(7, -1, -1):
            cursor = tree[cursor][(byte >> shift) & 1]
            if cursor == -1:
                return bytes(out), False

            symbol = tree[cursor][2]
            if symbol == -1:
                continue
            if symbol == 0:
                return bytes(out), True

            out.append(symbol)
            cursor = 0
            if len(out) >= limit:
                return bytes(out), False

    return bytes(out), False


def strip_formatting(decoded: bytes) -> tuple[str, str, str]:
    raw_text = decoded.decode('latin-1', errors='replace')
    visible_part, _, metadata_part = raw_text.partition('\x01')
    visible_text = re.sub(r'@.', '', visible_part)
    visible_text = visible_text.replace('\r\n', '\n').replace('\r', '\n')
    visible_text = '\n'.join(line.rstrip() for line in visible_text.splitlines()).strip()
    return visible_text, raw_text, metadata_part


def headword_matches(headword: str, visible_text: str, metadata_part: str) -> bool:
    target = normalize_headword(headword)
    if not target:
        return False
    return target in normalize_headword(visible_text) or target in normalize_headword(metadata_part)


def build_raw_dictionary(
    ido_path: Path,
    leo_path: Path,
    dll_path: Path,
    *,
    codebook_rva: int = DEFAULT_CODEBOOK_RVA,
    record_type: int | None = DEFAULT_RECORD_TYPE,
) -> dict[str, object]:
    leo_bytes = leo_path.read_bytes()
    tree = build_decoder_tree(build_decoder_table(dll_path, codebook_rva))
    index_entries = build_index(ido_path, leo_path, record_type=record_type)

    exported_entries: list[dict[str, object]] = []
    skipped_empty = 0
    skipped_headword = 0
    page_errors = 0

    for index_entry in index_entries:
        leo_offset = int(index_entry['leo_offset'])
        headword = str(index_entry['headword']).strip()

        try:
            page = read_page(leo_bytes, leo_offset)
        except ValueError:
            page_errors += 1
            continue

        if page.payload_len <= 0:
            skipped_empty += 1
            continue

        payload = leo_bytes[page.payload_offset : page.payload_offset + page.payload_len]
        decoded, decoded_complete = decode_payload(tree, payload)
        visible_text, raw_text, metadata_part = strip_formatting(decoded)

        if not visible_text or not any(char.isalpha() for char in visible_text):
            skipped_empty += 1
            continue
        if not headword_matches(headword, visible_text, metadata_part):
            skipped_headword += 1
            continue

        senses = [
            {'glosses': [line.strip()]}
            for line in visible_text.split('\n')
            if line.strip()
        ]
        if not senses:
            skipped_empty += 1
            continue

        exported_entries.append(
            {
                'headword': headword,
                'sourceOffset': leo_offset,
                'pageSpan': int(index_entry['page_span']),
                'decodedComplete': decoded_complete,
                'senses': senses,
            }
        )

    exported_entries.sort(key=lambda entry: (entry['headword'].casefold(), entry['sourceOffset']))

    return {
        'source': {
            'ido': str(ido_path),
            'leo': str(leo_path),
            'dll': str(dll_path),
            'codebook_rva': f'0x{codebook_rva:x}',
        },
        'stats': {
            'index_entries': len(index_entries),
            'exported_entries': len(exported_entries),
            'skipped_empty': skipped_empty,
            'skipped_headword': skipped_headword,
            'page_errors': page_errors,
        },
        'entries': exported_entries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build raw dictionary.json directly from IDO/LEO')
    parser.add_argument('--ido', default=str(ROOT / 'slagrods.ido'))
    parser.add_argument('--leo', default=str(ROOT / 'slagrods.leo'))
    parser.add_argument('--dll', default=str(DEFAULT_DLL))
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--codebook-rva', type=lambda raw: int(raw, 0), default=DEFAULT_CODEBOOK_RVA)
    parser.add_argument('--record-type', type=lambda raw: int(raw, 0), default=DEFAULT_RECORD_TYPE)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = build_raw_dictionary(
        Path(args.ido),
        Path(args.leo),
        Path(args.dll),
        codebook_rva=args.codebook_rva,
        record_type=args.record_type,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    print(
        f"built {payload['stats']['exported_entries']} raw entries from"
        f" {payload['stats']['index_entries']} index entries into {output_path}"
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
