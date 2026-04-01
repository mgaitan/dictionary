#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///

from __future__ import annotations

import argparse
import json
from pathlib import Path

from inspect_unilex import ROOT, read_page, scan_ido_records

ALLOWED_EXTRA = set("äöüÄÖÜßáéíóúÁÉÍÓÚñÑçÇàèìòùâêîôûëïæœøåÆŒØÅ")
ALLOWED_PUNCT = set(" ,-;/()[]'!?:")
DEFAULT_RECORD_TYPE = 0x8E


def looks_reasonable_headword(headword: str) -> bool:
    if not headword:
        return False
    if not headword[0].isalpha():
        return False

    for ch in headword:
        if ch.isascii() and (ch.isalnum() or ch in ALLOWED_PUNCT):
            continue
        if ch in ALLOWED_EXTRA:
            continue
        return False

    return True


def is_authentic_record(
    headword: str,
    leo_bytes: bytes,
    leo_offset: int,
    page_span: int,
    *,
    record_type: int,
    wanted_record_type: int | None,
) -> bool:
    if wanted_record_type is not None and record_type != wanted_record_type:
        return False
    if not looks_reasonable_headword(headword):
        return False

    try:
        page = read_page(leo_bytes, leo_offset)
    except ValueError:
        return False

    return page.payload_len > 0 and page.span == page_span


def build_index(
    ido_path: Path,
    leo_path: Path,
    *,
    record_type: int | None = DEFAULT_RECORD_TYPE,
) -> list[dict[str, object]]:
    ido_bytes = ido_path.read_bytes()
    leo_bytes = leo_path.read_bytes()
    items: list[dict[str, object]] = []
    seen: set[tuple[str, int, int, int]] = set()

    for record in scan_ido_records(ido_bytes, len(leo_bytes)):
        headword = record.headword.strip()
        if not is_authentic_record(
            headword,
            leo_bytes,
            record.leo_offset,
            record.page_span,
            record_type=record.record_type,
            wanted_record_type=record_type,
        ):
            continue

        signature = (
            headword,
            record.leo_offset,
            record.page_span,
            record.sort_tag,
        )
        if signature in seen:
            continue
        seen.add(signature)

        items.append(
            {
                "headword": headword,
                "leo_offset": record.leo_offset,
                "page_span": record.page_span,
                "tipo": record.record_type,
                "sort_tag": record.sort_tag,
                "ido_offset": record.offset,
            }
        )

    items.sort(
        key=lambda item: (
            str(item["headword"]).casefold(),
            int(item["leo_offset"]),
            int(item["ido_offset"]),
        )
    )
    return items


def cmd_export_index(args: argparse.Namespace) -> int:
    ido_path = ROOT / args.ido
    leo_path = ROOT / args.leo
    output_path = Path(args.output)

    items = build_index(ido_path, leo_path, record_type=args.record_type)
    payload = {
        "source": {
            "ido": str(ido_path),
            "leo": str(leo_path),
        },
        "filters": {
            "record_type": args.record_type,
        },
        "count": len(items),
        "entries": items,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"exported {len(items)} index entries to {output_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export UniLex index data")
    sub = parser.add_subparsers(dest="command", required=True)

    export_index = sub.add_parser(
        "export-index",
        help="export an authentic IDO/LEO headword index as JSON",
    )
    export_index.add_argument("--ido", default="slagrods.ido")
    export_index.add_argument("--leo", default="slagrods.leo")
    export_index.add_argument(
        "--record-type",
        type=lambda raw: int(raw, 0),
        default=DEFAULT_RECORD_TYPE,
        help="IDO record type to keep (default: 0x8e, primary headwords)",
    )
    export_index.add_argument(
        "--output",
        default="/home/tin/lab/UniLex/site/data/index.json",
    )
    export_index.set_defaults(func=cmd_export_index)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
