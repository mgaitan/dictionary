#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path('/home/tin/lab/UniLex/UniLex - Brandstetter Slaby/SlaGro')


@dataclass(frozen=True)
class LeoPage:
    offset: int
    field_00: int
    field_02: int
    flags: int
    field_06: int
    prev_offset: int
    prev_span: int
    next_offset: int
    next_span: int

    @property
    def span(self) -> int:
        if self.next_offset > self.offset:
            return self.next_offset - self.offset
        return 0

    @property
    def payload_offset(self) -> int:
        return self.offset + 20

    @property
    def payload_len(self) -> int:
        return max(self.span - 20, 0)


@dataclass(frozen=True)
class LeoFooter:
    footer_offset: int
    footer_size: int
    signature_offset: int
    signature: bytes

    @property
    def signature_text(self) -> str:
        return self.signature.decode('latin-1', errors='replace')


@dataclass(frozen=True)
class IdoRecord:
    offset: int
    leo_offset: int
    record_type: int
    page_span: int
    sort_tag: int
    headword: str
    guessed_headword: str
    kind: str


def read_page(data: bytes, offset: int) -> LeoPage:
    header = data[offset : offset + 20]
    if len(header) < 20:
        raise ValueError(f'short LEO header at 0x{offset:x}')
    return LeoPage(
        offset=offset,
        field_00=int.from_bytes(header[0:2], 'little'),
        field_02=int.from_bytes(header[2:4], 'little'),
        flags=int.from_bytes(header[4:6], 'little'),
        field_06=int.from_bytes(header[6:8], 'little'),
        prev_offset=int.from_bytes(header[8:12], 'little'),
        prev_span=int.from_bytes(header[12:14], 'little'),
        next_offset=int.from_bytes(header[14:18], 'little'),
        next_span=int.from_bytes(header[18:20], 'little'),
    )


def read_footer(data: bytes) -> LeoFooter:
    if len(data) < 8:
        raise ValueError('short LEO file')

    signature_offset = len(data) - 8
    signature = data[signature_offset : signature_offset + 4]
    footer_size = int.from_bytes(
        data[signature_offset + 4 : signature_offset + 8], 'little'
    )
    footer_offset = len(data) - footer_size

    if footer_offset < 0 or footer_offset > signature_offset:
        raise ValueError(f'invalid footer size 0x{footer_size:x}')

    return LeoFooter(
        footer_offset=footer_offset,
        footer_size=footer_size,
        signature_offset=signature_offset,
        signature=signature,
    )


def hexdump(data: bytes, start: int, length: int) -> str:
    chunk = data[start : start + length]
    lines: list[str] = []
    for row_start in range(0, len(chunk), 16):
        row = chunk[row_start : row_start + 16]
        hex_part = ' '.join(f'{byte:02x}' for byte in row)
        ascii_part = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in row)
        lines.append(f'0x{start + row_start:08x}  {hex_part:<47}  {ascii_part}')
    return '\n'.join(lines)


def decode_latin1_zstrip(data: bytes) -> str:
    return data.split(b'\x00', 1)[0].decode('latin-1', errors='replace')


def find_footer_string(data: bytes, needle: bytes) -> tuple[int, str] | None:
    pos = data.find(needle)
    if pos == -1:
        return None
    start = pos
    while start > 0 and data[start - 1] >= 32:
        start -= 1
    end = data.find(b'\x00', pos)
    if end == -1:
        end = len(data)
    return start, data[start:end].decode('latin-1', errors='replace')


def extract_c_strings(data: bytes, min_len: int) -> list[tuple[int, bytes]]:
    out: list[tuple[int, bytes]] = []
    start = None
    for idx, byte in enumerate(data):
        printable = byte in b'\t ' or 32 <= byte <= 126 or byte >= 0x80
        if printable:
            if start is None:
                start = idx
        else:
            if start is not None and idx - start >= min_len:
                out.append((start, data[start:idx]))
            start = None
    if start is not None and len(data) - start >= min_len:
        out.append((start, data[start:]))
    return out


def guess_ido_headword(
    raw_headword: str,
    sort_tag: int,
    previous_anchor: str,
    previous_record: IdoRecord | None,
) -> tuple[str, str]:
    lead = chr(sort_tag) if 65 <= sort_tag <= 122 else ''
    normalized = raw_headword
    if raw_headword and raw_headword[:1].islower() and lead.isalpha():
        normalized = lead + raw_headword

    if not raw_headword:
        guessed = previous_anchor or (previous_record.guessed_headword if previous_record else '')
        return guessed, 'continuation'

    if normalized[:1].isupper() or previous_record is None:
        return normalized, 'anchor'

    if previous_record.headword == '' and previous_anchor and normalized.isalpha():
        return previous_anchor + normalized, 'suffix'

    return normalized, 'fragment'


def looks_like_record(
    data: bytes,
    pos: int,
    leo_size: int,
    previous_anchor: str = '',
    previous_record: IdoRecord | None = None,
    *,
    allow_empty: bool = False,
    require_alpha: bool = True,
    allow_sort_zero: bool = False,
) -> IdoRecord | None:
    if pos + 9 >= len(data):
        return None
    if pos > 0 and data[pos - 1] != 0:
        return None

    leo_offset = int.from_bytes(data[pos : pos + 4], 'little')
    record_type = data[pos + 4]
    page_span = int.from_bytes(data[pos + 5 : pos + 7], 'little')
    sort_tag = data[pos + 7]

    if not (0 < leo_offset < leo_size):
        return None
    if not (0x80 <= record_type <= 0x9F):
        return None
    if sort_tag == 0 and not allow_sort_zero:
        return None

    end = data.find(b'\x00', pos + 8)
    if end == -1 or end - (pos + 8) > 160:
        return None
    if end == pos + 8 and not allow_empty:
        return None

    raw = data[pos + 8 : end]
    try:
        headword = raw.decode('latin-1')
    except UnicodeDecodeError:
        return None

    if require_alpha and headword and not any(ch.isalpha() for ch in headword):
        return None
    if any(ord(ch) < 32 for ch in headword):
        return None

    guessed_headword, kind = guess_ido_headword(
        headword,
        sort_tag,
        previous_anchor,
        previous_record,
    )

    return IdoRecord(
        offset=pos,
        leo_offset=leo_offset,
        record_type=record_type,
        page_span=page_span,
        sort_tag=sort_tag,
        headword=headword,
        guessed_headword=guessed_headword,
        kind=kind,
    )


def scan_ido_records(data: bytes, leo_size: int) -> Iterable[IdoRecord]:
    pos = 0
    seen: set[tuple[int, str]] = set()
    previous_anchor = ''
    previous_record: IdoRecord | None = None
    while pos < len(data) - 9:
        record = looks_like_record(data, pos, leo_size, previous_anchor, previous_record)
        if record is None:
            pos += 1
            continue

        key = (record.offset, record.headword)
        if key not in seen:
            seen.add(key)
            yield record
            previous_record = record
            if record.kind == 'anchor':
                previous_anchor = record.headword

        pos = data.find(b'\x00', pos + 8)
        if pos == -1:
            break
        pos += 1


def scan_ido_window(
    data: bytes,
    leo_size: int,
    center: int,
    before: int,
    after: int,
) -> Iterable[IdoRecord]:
    start = max(center - before, 0)
    end = min(center + after, len(data))
    seen: set[int] = set()
    previous_anchor = ''
    previous_record: IdoRecord | None = None

    for pos in range(start, max(end - 8, start)):
        record = looks_like_record(
            data,
            pos,
            leo_size,
            previous_anchor,
            previous_record,
            allow_empty=True,
            require_alpha=False,
        )
        if record is None or record.offset in seen:
            continue
        seen.add(record.offset)
        previous_record = record
        if record.kind == 'anchor':
            previous_anchor = record.headword
        yield record


def cmd_page(args: argparse.Namespace) -> int:
    leo_path = ROOT / args.leo
    data = leo_path.read_bytes()
    page = read_page(data, args.offset)
    print(f'file: {leo_path}')
    print(f'page offset: 0x{page.offset:x}')
    print(f'field_00: 0x{page.field_00:x} ({page.field_00})')
    print(f'field_02: 0x{page.field_02:x} ({page.field_02})')
    print(f'flags:    0x{page.flags:x}')
    print(f'field_06: 0x{page.field_06:x} ({page.field_06})')
    print(f'prev:     0x{page.prev_offset:x} span=0x{page.prev_span:x}')
    print(f'next:     0x{page.next_offset:x} span=0x{page.next_span:x}')
    print(f'span:     0x{page.span:x} ({page.span})')
    print(f'payload:  0x{page.payload_offset:x} len=0x{page.payload_len:x}')
    print()
    print('header:')
    print(hexdump(data, args.offset, 20))
    if page.payload_len:
        print()
        print('payload prefix:')
        print(hexdump(data, page.payload_offset, min(args.payload_bytes, page.payload_len)))
    return 0


def cmd_footer(args: argparse.Namespace) -> int:
    leo_path = ROOT / args.leo
    data = leo_path.read_bytes()
    footer = read_footer(data)
    footer_data = data[footer.footer_offset : footer.signature_offset + 8]

    print(f'file: {leo_path}')
    print(f'size:            0x{len(data):x} ({len(data)})')
    print(f'footer offset:   0x{footer.footer_offset:x}')
    print(f'footer size:     0x{footer.footer_size:x} ({footer.footer_size})')
    print(f'signature off:   0x{footer.signature_offset:x}')
    print(f'signature:       {footer.signature_text!r}')

    for label, needle in (
        ('title', b'Deutsch-Spanisch'),
        ('sorting', b'Standard\x00'),
        ('scope', b'DEUTSCH\x00'),
        ('footer tag', b'ACL\x00'),
    ):
        match = find_footer_string(footer_data, needle)
        if match is None:
            continue
        rel_offset, text = match
        print(f'{label:14} 0x{footer.footer_offset + rel_offset:x} {text}')

    print()
    print('footer head:')
    print(hexdump(data, footer.footer_offset, min(args.bytes, footer.footer_size)))
    print()
    print('footer tail:')
    tail_start = max(footer.footer_offset, footer.signature_offset + 8 - args.bytes)
    print(hexdump(data, tail_start, footer.signature_offset + 8 - tail_start))
    return 0


def cmd_ido_strings(args: argparse.Namespace) -> int:
    ido_path = ROOT / args.ido
    data = ido_path.read_bytes()
    items = extract_c_strings(data, args.min_len)
    count = 0
    for offset, raw in items:
        try:
            text = raw.decode('latin-1')
        except UnicodeDecodeError:
            continue
        if args.contains and args.contains.lower() not in text.lower():
            continue
        print(f'0x{offset:08x} {text}')
        count += 1
        if count >= args.limit:
            break
    return 0


def cmd_ido_records(args: argparse.Namespace) -> int:
    ido_path = ROOT / args.ido
    leo_path = ROOT / args.leo
    records = scan_ido_records(ido_path.read_bytes(), leo_path.stat().st_size)

    count = 0
    for record in records:
        haystack = ' '.join(filter(None, [record.headword, record.guessed_headword]))
        if args.contains and args.contains.lower() not in haystack.lower():
            continue
        print(
            f'0x{record.offset:08x} '
            f'leo=0x{record.leo_offset:08x} '
            f'type=0x{record.record_type:02x} '
            f'span=0x{record.page_span:04x} '
            f'tag=0x{record.sort_tag:02x} '
            f'raw={record.headword!r} '
            f'kind={record.kind} '
            f'guess={record.guessed_headword!r}'
        )
        count += 1
        if count >= args.limit:
            break
    return 0


def cmd_ido_window(args: argparse.Namespace) -> int:
    ido_path = ROOT / args.ido
    leo_path = ROOT / args.leo
    records = scan_ido_window(
        ido_path.read_bytes(),
        leo_path.stat().st_size,
        args.center,
        args.before,
        args.after,
    )
    count = 0
    for record in records:
        print(
            f'0x{record.offset:08x} '
            f'leo=0x{record.leo_offset:08x} '
            f'type=0x{record.record_type:02x} '
            f'span=0x{record.page_span:04x} '
            f'tag=0x{record.sort_tag:02x} '
            f'raw={record.headword!r} '
            f'kind={record.kind} '
            f'guess={record.guessed_headword!r}'
        )
        count += 1
        if count >= args.limit:
            break
    return 0


def cmd_ido_groups(args: argparse.Namespace) -> int:
    ido_path = ROOT / args.ido
    leo_path = ROOT / args.leo
    records = list(scan_ido_records(ido_path.read_bytes(), leo_path.stat().st_size))

    groups: list[tuple[str, list[IdoRecord]]] = []
    current_key = ''
    current_records: list[IdoRecord] = []

    for record in records:
        group_key = record.guessed_headword or record.headword
        if record.kind == 'anchor' and current_records:
            groups.append((current_key, current_records))
            current_records = []
        if record.kind == 'anchor':
            current_key = group_key
        elif not current_key:
            current_key = group_key
        current_records.append(record)

    if current_records:
        groups.append((current_key, current_records))

    count = 0
    for group_key, group_records in groups:
        haystack = ' '.join(filter(None, [group_key, *(r.headword for r in group_records)]))
        if args.contains and args.contains.lower() not in haystack.lower():
            continue

        print(f'{group_key or "<sin lema>"} ({len(group_records)} registros)')
        for record in group_records[: args.max_records]:
            print(
                '  '
                f'0x{record.offset:08x} '
                f'type=0x{record.record_type:02x} '
                f'span=0x{record.page_span:04x} '
                f'tag=0x{record.sort_tag:02x} '
                f'raw={record.headword!r} '
                f'kind={record.kind} '
                f'guess={record.guessed_headword!r}'
            )
        print()
        count += 1
        if count >= args.limit:
            break
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='Inspect UniLex LEO/IDO files')
    sub = parser.add_subparsers(dest='command', required=True)

    page = sub.add_parser('page', help='inspect a single LEO page')
    page.add_argument('offset', type=lambda value: int(value, 0))
    page.add_argument('--leo', default='slagrods.leo')
    page.add_argument('--payload-bytes', type=int, default=96)
    page.set_defaults(func=cmd_page)

    footer = sub.add_parser('footer', help='inspect the LEO footer')
    footer.add_argument('--leo', default='slagrods.leo')
    footer.add_argument('--bytes', type=int, default=128)
    footer.set_defaults(func=cmd_footer)

    ido_strings = sub.add_parser('ido-strings', help='dump candidate strings from an IDO file')
    ido_strings.add_argument('--ido', default='slagrods.ido')
    ido_strings.add_argument('--min-len', type=int, default=4)
    ido_strings.add_argument('--limit', type=int, default=80)
    ido_strings.add_argument('--contains')
    ido_strings.set_defaults(func=cmd_ido_strings)

    ido_records = sub.add_parser('ido-records', help='scan plausible IDO index records')
    ido_records.add_argument('--ido', default='slagrods.ido')
    ido_records.add_argument('--leo', default='slagrods.leo')
    ido_records.add_argument('--limit', type=int, default=80)
    ido_records.add_argument('--contains')
    ido_records.set_defaults(func=cmd_ido_records)

    ido_window = sub.add_parser('ido-window', help='inspect a raw window around an IDO offset')
    ido_window.add_argument('center', type=lambda value: int(value, 0))
    ido_window.add_argument('--ido', default='slagrods.ido')
    ido_window.add_argument('--leo', default='slagrods.leo')
    ido_window.add_argument('--before', type=int, default=64)
    ido_window.add_argument('--after', type=int, default=160)
    ido_window.add_argument('--limit', type=int, default=32)
    ido_window.set_defaults(func=cmd_ido_window)

    ido_groups = sub.add_parser('ido-groups', help='group nearby IDO records into logical lemmas')
    ido_groups.add_argument('--ido', default='slagrods.ido')
    ido_groups.add_argument('--leo', default='slagrods.leo')
    ido_groups.add_argument('--limit', type=int, default=40)
    ido_groups.add_argument('--max-records', type=int, default=8)
    ido_groups.add_argument('--contains')
    ido_groups.set_defaults(func=cmd_ido_groups)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())
