"""Discover DAMER keys in independent, resumable alphabetical segments."""

import argparse
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from discover_damer import BASE, wheel

# Actual wheel keys, not assumed alphabetic boundaries. Each segment ends at
# the first seed it encounters, so adjacent segments overlap at their boundary.
SEEDS = ("a", "earring", "iati", "m", "q'arachupa", "u")


def fetch(word: str) -> list[str]:
    request = Request(BASE + quote(word, safe=""), headers={"User-Agent": "DictionaryResearchBot/1.0"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=30) as response:
                return wheel(response.read().decode("utf-8"), word)
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)


def discover(path: Path, workers: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db, ThreadPoolExecutor(max_workers=workers) as pool:
        db.execute("CREATE TABLE IF NOT EXISTS keys (word TEXT PRIMARY KEY)")
        db.execute("CREATE TABLE IF NOT EXISTS segments (seed TEXT PRIMARY KEY, current TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0, boundary TEXT)")
        if "previous" not in {row[1] for row in db.execute("PRAGMA table_info(segments)")}:
            db.execute("ALTER TABLE segments ADD COLUMN previous TEXT")
        db.execute("CREATE TABLE IF NOT EXISTS unusable (word TEXT PRIMARY KEY)")
        db.executemany("INSERT OR IGNORE INTO segments(seed, current) VALUES (?, ?)", ((seed, seed) for seed in SEEDS))
        db.executemany("INSERT OR IGNORE INTO keys VALUES (?)", ((seed,) for seed in SEEDS))
        db.commit()
        active = {row[0]: row[1] for row in db.execute("SELECT seed, current FROM segments WHERE done = 0")}
        pending = {pool.submit(fetch, word): seed for seed, word in active.items()}
        failures = []
        count = 0
        while pending:
            future = next(as_completed(pending))
            seed = pending.pop(future)
            word = active[seed]
            try:
                following = future.result()
                boundary = next((key for key in following if key in SEEDS), None)
                if boundary:
                    following = following[:following.index(boundary) + 1]
                unusable = {row[0] for row in db.execute("SELECT word FROM unusable")}
                candidates = [key for key in following if key[-1].isalnum() and key not in unusable]
                if not boundary and not candidates:
                    raise ValueError(f"Sin siguiente lema utilizable para {word!r}")
                next_word = candidates[-1] if candidates else word
                with db:
                    db.executemany("INSERT OR IGNORE INTO keys VALUES (?)", ((key,) for key in following))
                    db.execute("UPDATE segments SET current = ?, done = ?, boundary = ?, previous = ? WHERE seed = ?", (next_word, int(boundary is not None), boundary, word, seed))
                count += 1
                if boundary:
                    print(f"Tramo {seed!r} cerrado en {boundary!r}", flush=True)
                else:
                    active[seed] = next_word
                    pending[pool.submit(fetch, next_word)] = seed
                if count % 100 == 0:
                    total = db.execute("SELECT COUNT(*) FROM keys").fetchone()[0]
                    print(f"{count} consultas, {total} claves", flush=True)
            except Exception as exc:
                previous = db.execute("SELECT previous FROM segments WHERE seed = ?", (seed,)).fetchone()[0]
                if isinstance(exc, ValueError) and previous and previous != word:
                    with db:
                        db.execute("INSERT OR IGNORE INTO unusable VALUES (?)", (word,))
                        db.execute("UPDATE segments SET current = ?, previous = NULL WHERE seed = ?", (previous, seed))
                    active[seed] = previous
                    pending[pool.submit(fetch, previous)] = seed
                    print(f"Lema inaccesible {word!r}; reanudando desde {previous!r}", flush=True)
                    continue
                failures.append((seed, word, str(exc)))
                print(f"Error en tramo {seed!r}, lema {word!r}: {exc}", flush=True)
        total = db.execute("SELECT COUNT(*) FROM keys").fetchone()[0]
        segments = db.execute("SELECT seed, boundary FROM segments WHERE done = 1").fetchall()
        print(f"{total} claves; {len(segments)}/{len(SEEDS)} tramos cerrados", flush=True)
        links = dict(segments)
        visited = set()
        current = SEEDS[0]
        while current in links and current not in visited:
            visited.add(current)
            current = links[current]
        if failures or len(visited) != len(SEEDS) or current != SEEDS[0]:
            raise SystemExit("El recorrido no está completo; corregí los errores y volvé a ejecutar.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, default=Path("site/data/damer-keys.sqlite"))
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= len(SEEDS):
        parser.error(f"--workers debe estar entre 1 y {len(SEEDS)}")
    discover(args.sqlite, args.workers)


if __name__ == "__main__":
    main()
