#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///

from __future__ import annotations

import argparse
import json
from pathlib import Path


def to_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def canonicalize_senses(raw_senses: list[object]) -> list[dict[str, object]]:
    senses: list[dict[str, object]] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...], str]] = set()

    for raw_sense in raw_senses:
        if isinstance(raw_sense, str):
            sense = {
                "tags": [],
                "source": "",
                "glosses": [raw_sense.strip()],
            }
        else:
            glosses = to_string_list(
                raw_sense.get("glosses")
                or raw_sense.get("definitions")
                or raw_sense.get("translations")
                or raw_sense.get("translation")
            )
            tags = []
            for field in ("tags", "labels", "grammar", "contexts"):
                tags.extend(to_string_list(raw_sense.get(field)))
            source = str(
                raw_sense.get("source")
                or raw_sense.get("sourceText")
                or raw_sense.get("sourceNote")
                or ""
            ).strip()
            sense = {
                "tags": tags,
                "source": source,
                "glosses": glosses,
            }

        signature = (
            tuple(sense["tags"]),
            tuple(sense["glosses"]),
            sense["source"],
        )
        if not sense["glosses"] or signature in seen:
            continue
        seen.add(signature)
        senses.append(sense)

    return senses


def build_dictionary(
    raw_dictionary_path: Path,
    index_path: Path,
    *,
    keep_unmatched: bool = False,
) -> dict[str, object]:
    raw_payload = json.loads(raw_dictionary_path.read_text(encoding="utf-8"))
    raw_entries = raw_payload["entries"]
    index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    index_by_offset = {
        int(entry["leo_offset"]): entry for entry in index_payload["entries"]
    }

    grouped: dict[str, dict[str, object]] = {}
    matched_offsets = 0
    unmatched_offsets = 0

    for raw_entry in raw_entries:
        raw_headword = str(raw_entry.get("headword") or "").strip()
        source_offset = raw_entry.get("sourceOffset")
        index_entry = index_by_offset.get(source_offset)

        if index_entry is None:
            unmatched_offsets += 1
            if not keep_unmatched or not raw_headword:
                continue
            headword = raw_headword
        else:
            matched_offsets += 1
            headword = str(index_entry["headword"]).strip()

        if not headword:
            continue

        senses = canonicalize_senses(raw_entry.get("senses") or [])
        if not senses:
            continue

        entry = grouped.setdefault(
            headword,
            {
                "headword": headword,
                "variants": [],
                "sourceOffsets": [],
                "decodedComplete": False,
                "senses": [],
                "_sense_keys": set(),
            },
        )

        if (
            raw_headword
            and raw_headword != headword
            and raw_headword not in entry["variants"]
        ):
            entry["variants"].append(raw_headword)

        if source_offset is not None and source_offset not in entry["sourceOffsets"]:
            entry["sourceOffsets"].append(source_offset)

        entry["decodedComplete"] = bool(
            entry["decodedComplete"] or raw_entry.get("decodedComplete")
        )

        for sense in senses:
            sense_key = (
                tuple(sense["tags"]),
                tuple(sense["glosses"]),
                sense["source"],
            )
            if sense_key in entry["_sense_keys"]:
                continue
            entry["_sense_keys"].add(sense_key)
            entry["senses"].append(sense)

    entries: list[dict[str, object]] = []
    for entry in grouped.values():
        entry.pop("_sense_keys", None)
        entry["variants"].sort(key=str.casefold)
        entry["sourceOffsets"].sort()
        entry["senses"].sort(
            key=lambda sense: (
                " ".join(sense["glosses"]).casefold(),
                " ".join(sense["tags"]).casefold(),
                sense["source"].casefold(),
            )
        )
        entries.append(entry)

    entries.sort(key=lambda entry: entry["headword"].casefold())

    return {
        "source": {
            "raw_dictionary": str(raw_dictionary_path),
            "index": str(index_path),
        },
        "stats": {
            "raw_entries": len(raw_entries),
            "matched_offsets": matched_offsets,
            "unmatched_offsets": unmatched_offsets,
            "grouped_entries": len(entries),
        },
        "entries": entries,
    }


def cmd_build(args: argparse.Namespace) -> int:
    payload = build_dictionary(
        Path(args.raw_dictionary),
        Path(args.index),
        keep_unmatched=args.keep_unmatched,
    )
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "built"
        f" {payload['stats']['grouped_entries']} grouped entries"
        f" from {payload['stats']['raw_entries']} raw entries"
        f" into {output_path}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build cleaned site dictionary data")
    parser.add_argument(
        "--raw-dictionary",
        default="/home/tin/lab/UniLex/site/data/dictionary.json",
    )
    parser.add_argument(
        "--index",
        default="/home/tin/lab/UniLex/site/data/index.json",
    )
    parser.add_argument(
        "--output",
        default="/home/tin/lab/UniLex/site/data/dictionary-indexed.json",
    )
    parser.add_argument(
        "--keep-unmatched",
        action="store_true",
        help="keep decoded entries whose sourceOffset is absent from the IDO index",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return cmd_build(args)


if __name__ == "__main__":
    raise SystemExit(main())
