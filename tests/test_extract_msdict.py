from __future__ import annotations

import sys
import zlib
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from extract_msdict import (
    article_text_lines,
    clean_display_headword,
    decode_article,
    parse_ber,
)


def encode_length(length: int) -> bytes:
    groups = [length & 0x7F]
    length >>= 7
    while length:
        groups.append(0x80 | (length & 0x7F))
        length >>= 7
    return bytes(reversed(groups))


def ber(tag: int, value: bytes, *, constructed: bool = False) -> bytes:
    first = 0x40 | tag | (0x20 if constructed else 0)
    return bytes([first]) + encode_length(len(value)) + value


def shifted_record(payload: bytes, shift: int, prefix_length: int) -> tuple[bytes, int]:
    compressor = zlib.compressobj(level=9, wbits=-15)
    compressed = compressor.compress(payload) + compressor.flush()
    prefix = bytearray(compressed[:prefix_length])
    prefix[-1] &= (1 << (8 - shift)) - 1

    continuation = bytearray()
    previous = compressed[prefix_length - 1]
    low_mask = (1 << (8 - shift)) - 1
    shift_mask = (1 << shift) - 1
    for current in compressed[prefix_length:]:
        continuation.append(
            ((previous >> (8 - shift)) & shift_mask) | ((current & low_mask) << shift)
        )
        previous = current
    continuation.append((previous >> (8 - shift)) & shift_mask)

    branch_offset = 3 + prefix_length
    record = (
        bytes([shift << 5]) + prefix_length.to_bytes(2, "big") + prefix + continuation
    )
    return record, branch_offset


def test_parse_ber_and_extract_visible_article_lines() -> None:
    language = ber(15, b"ES")
    text = bytes([4]) + encode_length(4) + b"casa"
    span = ber(3, language + text, constructed=True)
    root = ber(13, span, constructed=True)

    node = parse_ber(root)

    assert node.tag == 13
    assert article_text_lines(root, "utf-8") == ["casa"]


def test_decode_article_reassembles_bit_shifted_deflate_stream() -> None:
    payload = ("dictionary / diccionario; house / casa\n" * 20).encode()
    record, branch_offset = shifted_record(payload, shift=3, prefix_length=7)

    assert decode_article(record, branch_offset) == payload


def test_clean_display_headword_removes_matching_disambiguator() -> None:
    assert clean_display_headword("house2", "house(2)") == "house"
    assert clean_display_headword("correr [Verb Table E1]", "correr") == "correr"
    assert (
        clean_display_headword("ache2[Vocabulary notes (English)]", "ache(2)") == "ache"
    )
    assert clean_display_headword("A1", "A1") == "A1"
