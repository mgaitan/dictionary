"""Discover DAMER keys using the alphabetical wheel."""

import argparse
import re
import sqlite3
from html import unescape
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

BASE = "https://www.asale.org/damer/"


def wheel(page: str, word: str) -> list[str]:
    match = re.search(r"<ul\b[^>]*class=['\"]rueda['\"][^>]*>(.*?)</ul>", page, re.I | re.S)
    if not match:
        raise ValueError(f"No se encontró la rueda para {word!r}")
    items = re.findall(r"<li\b[^>]*>(.*?)</li>", match.group(1), re.I | re.S)
    keys = []
    for item in items:
        link = re.search(r"<a\b[^>]*>(.*?)</a>", item, re.I | re.S)
        if link:
            keys.append(unescape(re.sub(r"<[^>]+>", "", link.group(1))).strip())
        else:
            current = re.search(r"<b\b[^>]*>(.*?)</b>", item, re.I | re.S)
            if not current:
                raise ValueError(f"Elemento inesperado en la rueda de {word!r}")
            keys.append(unescape(re.sub(r"<[^>]+>", "", current.group(1))).strip())
    if word in keys and keys.index(word) + 1 < len(keys):
        return keys[keys.index(word) + 1:]
    raise ValueError(f"No se encontraron lemas siguientes para {word!r}")


def discover(path: Path, limit: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE IF NOT EXISTS keys (word TEXT PRIMARY KEY)")
        db.execute("CREATE TABLE IF NOT EXISTS progress (id INTEGER PRIMARY KEY CHECK (id = 1), next_word TEXT NOT NULL, done INTEGER NOT NULL)")
        db.execute("INSERT OR IGNORE INTO progress VALUES (1, 'a', 0)")
        db.execute("INSERT OR IGNORE INTO keys VALUES ('a')")
        db.commit()
        word, done = db.execute("SELECT next_word, done FROM progress").fetchone()
        count = 0
        while not done and (limit is None or count < limit):
            request = Request(BASE + quote(word, safe=""), headers={"User-Agent": "DictionaryResearchBot/1.0"})
            with urlopen(request, timeout=30) as response:
                following = wheel(response.read().decode("utf-8"), word)
            if "a" in following:
                following = following[:following.index("a")]
                done = True
            candidates = [key for key in following if key[-1].isalnum()]
            if not done and not candidates:
                raise ValueError(f"No hay un lema siguiente apto para continuar desde {word!r}")
            next_word = candidates[-1] if candidates else word
            with db:
                db.executemany("INSERT OR IGNORE INTO keys VALUES (?)", ((key,) for key in following))
                db.execute("UPDATE progress SET next_word = ?, done = ?", (next_word, int(done)))
            count += 1
            total = db.execute("SELECT COUNT(*) FROM keys").fetchone()[0]
            print(f"{count} consultas, {total} claves: {word} → {next_word}", flush=True)
            word = next_word
        if done:
            print("Recorrido completo.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=Path("site/data/damer-keys.sqlite"))
    parser.add_argument("--limit", type=int, help="Máximo de consultas en esta ejecución")
    args = parser.parse_args()
    if args.limit is not None and args.limit < 1:
        parser.error("--limit debe ser positivo")
    discover(args.sqlite, args.limit)


if __name__ == "__main__":
    main()
