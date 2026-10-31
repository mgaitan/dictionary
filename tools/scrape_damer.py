"""Download DAMER articles by following the alphabetical wheel."""

from __future__ import annotations

import argparse
import re
import sqlite3
import time
from html import unescape
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit
from urllib.request import Request, urlopen

BASE = "https://www.asale.org/damer/"


def parse_page(page: str, word: str) -> tuple[str, str]:
    articles = re.findall(
        r"<entry\b[^>]*>.*?</entry\s*>", page, re.IGNORECASE | re.DOTALL
    )
    wheel = re.search(
        r"<ul\b[^>]*class=['\"]rueda['\"][^>]*>(.*?)</ul>",
        page,
        re.IGNORECASE | re.DOTALL,
    )
    if not articles or not wheel:
        raise ValueError(f"No se encontraron artículos o rueda para {word!r}")
    items = re.findall(
        r"<li\b[^>]*>(.*?)</li>", wheel.group(1), re.IGNORECASE | re.DOTALL
    )
    for i, item in enumerate(items):
        current = re.search(r"<b\b[^>]*>(.*?)</b>", item, re.IGNORECASE | re.DOTALL)
        if (
            current
            and unescape(re.sub(r"<[^>]+>", "", current.group(1))).strip() == word
        ):
            following = items[(i + 1) % len(items)]
            link = re.search(r"href=['\"]([^'\"]+)['\"]", following, re.IGNORECASE)
            if link:
                path = urlsplit(unescape(link.group(1))).path
                if path.startswith("/damer/"):
                    return "\n".join(articles), unquote(path[len("/damer/") :])
    raise ValueError(f"No se encontró el siguiente lema de {word!r}")


def scrape(path: Path, limit: int | None = None) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS pages (word TEXT PRIMARY KEY, html TEXT NOT NULL, next_word TEXT NOT NULL)"
        )
        word = "a"
        count = 0
        visited: set[str] = set()
        while True:
            if word in visited:
                raise ValueError(f"La rueda volvió inesperadamente a {word!r}")
            visited.add(word)
            row = db.execute(
                "SELECT next_word FROM pages WHERE word = ?", (word,)
            ).fetchone()
            if row:
                word = row[0]
                if word == "a":
                    break
                continue
            if limit is not None and count >= limit:
                break
            request = Request(
                BASE + quote(word, safe=""),
                headers={"User-Agent": "DictionaryResearchBot/1.0"},
            )
            with urlopen(request, timeout=30) as response:
                page = response.read().decode("utf-8")
            article, next_word = parse_page(page, word)
            with db:
                db.execute(
                    "INSERT INTO pages VALUES (?, ?, ?)", (word, article, next_word)
                )
            count += 1
            print(f"{count}: {word} → {next_word}", flush=True)
            word = next_word
            if word == "a" or (limit is not None and count >= limit):
                break
            time.sleep(0.5)  # ASALE robots.txt: Crawl-delay: 5
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite", type=Path, default=Path("site/data/damer-raw.sqlite")
    )
    parser.add_argument(
        "--limit", type=int, help="Máximo de páginas nuevas en esta ejecución"
    )
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit debe ser positivo")
    scrape(args.sqlite, args.limit)


if __name__ == "__main__":
    main()
