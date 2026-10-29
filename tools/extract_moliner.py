"""Export the original DUE 3.0 XML without running its installer.

Reads Lucene 2.2 compound files; encrypted files use the block layout from
CryptDirectory/AlgDUE in the supplied due.jar. Requires the openssl executable.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import struct
import subprocess
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def decrypt_cfs(data: bytes) -> bytes:
    if data[:1] != b"\0":
        return data
    if len(data) < 1032 or (len(data) - 8) % 1024:
        raise ValueError("Invalid encrypted DUE compound file length")
    size = struct.unpack(">Q", data[:8])[0]
    digest = [n if n < 128 else n - 256 for n in hashlib.sha256(b"ps1").digest()]
    # Java byte arithmetic and shift distances from AlgDUE.dxx.
    key = bytes(
        ((digest[i] + digest[4] * digest[i + 2]) << (digest[i + 4] & 31)) & 255
        for i in range(16)
    )
    raw = subprocess.run(
        ["openssl", "enc", "-d", "-aes-128-ecb", "-nopad", "-K", key.hex()],
        input=data[8:],
        capture_output=True,
        check=True,
    ).stdout
    if any(raw[i] != 1 for i in range(1023, len(raw), 1024)):
        raise ValueError("Invalid DUE block padding")
    plain = b"".join(raw[i : i + 1023] for i in range(0, len(raw), 1024))
    if not len(plain) - 1023 < size <= len(plain):
        raise ValueError("Invalid decrypted DUE size")
    return plain[:size]


class Reader(io.BytesIO):
    def take(self, size: int) -> bytes:
        value = self.read(size)
        if len(value) != size:
            raise ValueError("Truncated Lucene data")
        return value

    def vint(self) -> int:
        value = 0
        for shift in range(0, 35, 7):
            byte = self.take(1)[0]
            value |= (byte & 127) << shift
            if not byte & 128:
                return value
        raise ValueError("Invalid Lucene VInt")

    def string(self) -> str:
        # Lucene 2.2 lengths count UTF-16 code units (modified UTF-8).
        chunks = []
        for _ in range(self.vint()):
            first = self.take(1)
            extra = 0 if first[0] < 128 else (1 if first[0] < 224 else 2)
            chunks.append(first + self.take(extra))
        return b"".join(chunks).decode("utf-8", errors="surrogatepass")


def read_documents(path: Path):
    data = decrypt_cfs(path.read_bytes())
    reader = Reader(data)
    offsets = {}
    for _ in range(reader.vint()):
        offset = struct.unpack(">Q", reader.take(8))[0]
        name = reader.string()
        if not reader.tell() <= offset < len(data):
            raise ValueError("Invalid compound file offset")
        offsets[name] = offset
    bounds = sorted(offsets.values()) + [len(data)]
    parts = {
        name.rsplit(".", 1)[1]: data[start : bounds[bounds.index(start) + 1]]
        for name, start in offsets.items()
    }
    fields_reader = Reader(parts["fnm"])
    fields = []
    for _ in range(fields_reader.vint()):
        fields.append(fields_reader.string())
        fields_reader.take(1)
    index = parts["fdx"]
    if len(index) % 8:
        raise ValueError("Invalid stored fields index")
    positions = [pos[0] for pos in struct.iter_unpack(">Q", index)]
    if not positions or positions[0] != 0 or positions != sorted(set(positions)):
        raise ValueError("Invalid stored field positions")
    reader = Reader(parts["fdt"])
    for position, end in zip(positions, positions[1:] + [len(parts["fdt"])]):
        reader.seek(position)
        document = {}
        for _ in range(reader.vint()):
            field = fields[reader.vint()]
            flags = reader.take(1)[0]
            if flags & ~7:
                raise ValueError(f"Unsupported field flags: {flags}")
            if flags & 4:
                value = zlib.decompress(reader.take(reader.vint())).decode("utf-8")
            elif flags & 2:
                raise ValueError("Binary stored fields are not DUE XML")
            else:
                value = reader.string()
            if field in document:
                raise ValueError(f"Repeated stored field: {field}")
            document[field] = value
        if reader.tell() != end:
            raise ValueError("Stored fields do not match document boundary")
        yield document


def export_articles(source: Path, output: Path) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    count = 0
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            for document in read_documents(source):
                article = {
                    "id": document["idEntrada"],
                    "lemma_id": document["idLema"],
                    "headword": document["lema"],
                    "lemma_xml": document["xmlLema"],
                    "entry_xml": document["xmlEntrada"],
                }
                stream.write(json.dumps(article, ensure_ascii=False) + "\n")
                count += 1
        if not count:
            raise ValueError("No articles found")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return count


def extract_fonts(installer: Path, output: Path) -> None:
    """Recover the original Greek fonts from embedded zlib streams."""
    data = installer.read_bytes()
    found = {}
    for match in re.finditer(b"\x78[\x01\x9c\xda]", data):
        try:
            inflater = zlib.decompressobj()
            font = inflater.decompress(
                data[match.start() : match.start() + 2_000_000], 2_000_000
            )
        except zlib.error:
            continue
        if not inflater.eof or not font.startswith(b"\0\1\0\0"):
            continue
        for name in ("detede1", "detede2"):
            if name.encode() in font or name.encode("utf-16-be") in font:
                found[name] = font
    if set(found) != {"detede1", "detede2"}:
        raise ValueError("The installer does not contain both DUE Greek fonts")
    output.mkdir(parents=True, exist_ok=True)
    for name, data in found.items():
        (output / (name + ".ttf")).write_bytes(data)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / "site/data/moliner-articles.jsonl"
    )
    parser.add_argument(
        "--fonts-from", type=Path, help="Also extract fonts from the Linux installer"
    )
    parser.add_argument(
        "--fonts-output", type=Path, default=ROOT / "dictionary/static/fonts"
    )
    args = parser.parse_args()
    if args.source is None:
        matches = list(ROOT.glob("Diccionario*/**/Setup/index/lemas/_*.cfs"))
        if len(matches) != 1:
            parser.error("Supply --source with the DUE index/lemas compound file")
        args.source = matches[0]
    count = export_articles(args.source, args.output)
    print(f"Exported {count:,} original XML articles to {args.output}")
    if args.fonts_from:
        extract_fonts(args.fonts_from, args.fonts_output)
        print(f"Extracted detede1/detede2 to {args.fonts_output}")


if __name__ == "__main__":
    main()
