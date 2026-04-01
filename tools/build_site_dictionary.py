#!/usr/bin/env -S uv run
# /// script
# dependencies = []
# ///

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TOP_LEVEL_HEADING_RE = re.compile(r"^[A-Z]\)\s+")
NUMBERED_HEADING_RE = re.compile(r"^\d+\.\s+")
LETTER_HEADING_RE = re.compile(r"^[a-z]\)\s+")


def normalize_headword(value: str) -> str:
    return re.sub(r"[^\w]+", "", str(value).casefold().replace("·", ""))


def to_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def extract_raw_lines(raw_senses: list[object]) -> list[str]:
    lines: list[str] = []
    for raw_sense in raw_senses:
        if isinstance(raw_sense, str):
            text = raw_sense.strip()
            if text:
                lines.append(text)
            continue

        source = str(
            raw_sense.get("source")
            or raw_sense.get("sourceText")
            or raw_sense.get("sourceNote")
            or ""
        ).strip()
        if source:
            lines.append(source)

        for field in ("glosses", "definitions", "translations", "translation"):
            for item in to_string_list(raw_sense.get(field)):
                lines.append(item)

    return [line for line in lines if line.strip()]


def build_structured_senses(lines: list[str]) -> list[dict[str, object]]:
    if not lines:
        return []

    senses: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    level_one = ""
    level_two = ""
    level_three = ""

    def flush() -> None:
        nonlocal current
        if current and current["glosses"]:
            senses.append(current)
        current = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        if TOP_LEVEL_HEADING_RE.match(line):
            flush()
            level_one = line
            level_two = ""
            level_three = ""
            continue

        if NUMBERED_HEADING_RE.match(line):
            flush()
            level_two = line
            level_three = ""
            continue

        if LETTER_HEADING_RE.match(line):
            flush()
            level_three = line
            continue

        if current is None:
            current = {
                "tags": [],
                "source": " · ".join(
                    heading
                    for heading in (level_one, level_two, level_three)
                    if heading
                ),
                "glosses": [],
            }

        current["glosses"].append(line)

    flush()

    if senses:
        return senses

    return [
        {
            "tags": [],
            "source": "",
            "glosses": lines,
        }
    ]


def is_redundant_headword_line(headword: str, line: str) -> bool:
    if not headword or not line:
        return False
    normalized_line = normalize_headword(line.rstrip(":"))
    return normalized_line == normalize_headword(headword)


def canonicalize_senses(
    raw_senses: list[object],
    *,
    headword: str = "",
) -> list[dict[str, object]]:
    raw_lines = extract_raw_lines(raw_senses)
    if raw_lines and is_redundant_headword_line(headword, raw_lines[0]):
        raw_lines = raw_lines[1:]
    if raw_lines:
        return build_structured_senses(raw_lines)

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


def should_keep_variant(headword: str, candidate: str) -> bool:
    candidate = candidate.strip()
    if not candidate or candidate == headword:
        return False

    headword_key = normalize_headword(headword)
    candidate_key = normalize_headword(candidate)
    if not headword_key or not candidate_key or candidate_key == headword_key:
        return False
    if len(candidate_key) < 3:
        return False
    if candidate_key in headword_key or headword_key in candidate_key:
        return True

    prefix = 0
    for left, right in zip(headword_key, candidate_key):
        if left != right:
            break
        prefix += 1

    return prefix >= 4


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
        index_headword = ""
        source_offset = raw_entry.get("sourceOffset")
        index_entry = index_by_offset.get(source_offset)

        if index_entry is None:
            unmatched_offsets += 1
            if not keep_unmatched or not raw_headword:
                continue
            headword = raw_headword
        else:
            matched_offsets += 1
            index_headword = str(index_entry["headword"]).strip()
            headword = raw_headword or index_headword

        if not headword:
            continue

        senses = canonicalize_senses(
            raw_entry.get("senses") or [],
            headword=headword,
        )
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
            and should_keep_variant(headword, raw_headword)
            and raw_headword not in entry["variants"]
        ):
            entry["variants"].append(raw_headword)
        if (
            index_headword
            and index_headword != headword
            and should_keep_variant(headword, index_headword)
            and index_headword not in entry["variants"]
        ):
            entry["variants"].append(index_headword)

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
