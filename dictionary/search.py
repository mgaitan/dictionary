from __future__ import annotations

import html
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from markupsafe import Markup

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "site" / "data"
PAGE_LIMIT = 25

GLOSS_TOKEN_RE = re.compile(
    r"(\[[^\]]+\]|<[^>]+>|(?<![\w·])(?:m|f|n|pl|mpl|fpl|adj|adv|vt|vi|vr|vtr|pron|prep|conj|interj|num|sg|subst|tr|intr)(?![\w]))",
    re.IGNORECASE,
)
GLOSS_MARKER_RE = re.compile(r"^\s*([a-z]\))\s*", re.IGNORECASE)
GRAMMAR_TOKEN_RE = re.compile(
    r"^(m|f|n|pl|mpl|fpl|adj|adv|vt|vi|vr|vtr|pron|prep|conj|interj|num|sg|subst|tr|intr)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DictionaryConfig:
    id: str
    database_path: Path
    title: str
    description: str
    direction_label: str
    search_label: str
    placeholder: str
    examples: tuple[str, ...]
    hero_lead: str


DICTIONARIES: dict[str, DictionaryConfig] = {
    "de-es": DictionaryConfig(
        id="de-es",
        database_path=DATA_DIR / "dictionary.sqlite",
        title="Diccionario alemán-español",
        description="Buscador FastAPI + SQLite para el diccionario alemán-español.",
        direction_label="Alemán -> español",
        search_label="Palabra alemana",
        placeholder="Ej. Tabakqualm, Macher, verabschieden",
        examples=("Macher", "Machbarkeit", "Tabakqualm", "Verabschiedung"),
        hero_lead="",
    ),
    "es-de": DictionaryConfig(
        id="es-de",
        database_path=DATA_DIR / "es-de-dictionary.sqlite",
        title="Diccionario español-alemán",
        description="Buscador FastAPI + SQLite para el diccionario español-alemán.",
        direction_label="Español -> alemán",
        search_label="Palabra española",
        placeholder="Ej. hacer, mujer, antaño, abadesa",
        examples=("hacer", "mujer", "antaño", "abadesa"),
        hero_lead="",
    ),
}


def get_dictionary(dictionary_id: str | None) -> DictionaryConfig:
    if dictionary_id and dictionary_id in DICTIONARIES:
        return DICTIONARIES[dictionary_id]
    return DICTIONARIES["de-es"]


def normalize_for_search(value: str) -> str:
    trimmed = value.strip()
    if not trimmed:
        return ""

    folded = trimmed.replace("ß", "ss").replace("ẞ", "ss").replace("·", "")
    ascii_text = unicodedata.normalize("NFD", folded)
    ascii_text = "".join(
        char for char in ascii_text if unicodedata.category(char) != "Mn"
    )
    ascii_text = ascii_text.lower()
    ascii_text = re.sub(r"[^a-z0-9]+", " ", ascii_text)
    return re.sub(r"\s+", " ", ascii_text).strip()


def open_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def load_stats(connection: sqlite3.Connection) -> dict[str, int]:
    entry_count = int(connection.execute("SELECT COUNT(*) FROM entries").fetchone()[0])
    sense_count = int(connection.execute("SELECT COUNT(*) FROM senses").fetchone()[0])
    return {
        "entries": entry_count,
        "senses": sense_count,
    }


def decode_json_list(value: str) -> list[str]:
    import json

    decoded = json.loads(value)
    if not isinstance(decoded, list):
        return []
    return [str(item).strip() for item in decoded if str(item).strip()]


def search_entries(
    connection: sqlite3.Connection,
    query: str,
    normalized_query: str,
    limit: int = PAGE_LIMIT,
    page: int = 1,
) -> dict[str, Any]:
    prefix = normalized_query + "%"
    contains = "%" + normalized_query + "%"
    offset = max(0, (page - 1) * limit)

    total = int(
        connection.execute(
            """
            SELECT COUNT(DISTINCT e.id)
            FROM search_terms st
            INNER JOIN entries e ON e.id = st.entry_id
            WHERE st.normalized_term LIKE ?
            """,
            (contains,),
        ).fetchone()[0]
    )

    if total == 0:
        return {
            "total": 0,
            "page": 1,
            "entries": [],
        }

    entry_rows = connection.execute(
        """
        SELECT
            e.id,
            e.headword,
            e.decoded_complete,
            CASE
                WHEN e.normalized_headword = ? THEN -1
                ELSE 0
            END AS exact_headword_rank,
            MIN(
                CASE
                    WHEN st.normalized_term = ? THEN 0
                    WHEN st.normalized_term LIKE ? THEN 1
                    ELSE 2
                END
            ) AS rank,
            MIN(LENGTH(st.normalized_term)) AS term_length
        FROM search_terms st
        INNER JOIN entries e ON e.id = st.entry_id
        WHERE st.normalized_term LIKE ?
        GROUP BY e.id, e.headword, e.decoded_complete
        ORDER BY exact_headword_rank ASC, rank ASC, term_length ASC, e.normalized_headword ASC
        LIMIT ?
        OFFSET ?
        """,
        (normalized_query, normalized_query, prefix, contains, limit, offset),
    ).fetchall()

    if not entry_rows:
        return {
            "total": total,
            "page": page,
            "entries": [],
        }

    entry_ids = [int(row["id"]) for row in entry_rows]
    placeholders = ",".join("?" for _ in entry_ids)
    sense_rows = connection.execute(
        f"""
        SELECT entry_id, sense_index, source, glosses_json, tags_json
        FROM senses
        WHERE entry_id IN ({placeholders})
        ORDER BY entry_id ASC, sense_index ASC
        """,
        entry_ids,
    ).fetchall()

    senses_by_entry: dict[int, list[dict[str, Any]]] = {}
    for row in sense_rows:
        senses_by_entry.setdefault(int(row["entry_id"]), []).append(
            {
                "source": str(row["source"]),
                "glosses": decode_json_list(str(row["glosses_json"])),
                "tags": decode_json_list(str(row["tags_json"])),
            }
        )

    entries: list[dict[str, Any]] = []
    for row in entry_rows:
        entry_id = int(row["id"])
        entries.append(
            {
                "id": entry_id,
                "headword": str(row["headword"]),
                "decoded_complete": bool(row["decoded_complete"]),
                "senses": senses_by_entry.get(entry_id, []),
            }
        )

    return {
        "total": total,
        "page": page,
        "entries": entries,
    }


def find_unresolved_index_entry(
    connection: sqlite3.Connection,
    normalized_query: str,
    results: list[dict[str, Any]],
) -> dict[str, Any] | None:
    for entry in results:
        if normalize_for_search(str(entry["headword"])) == normalized_query:
            return None

    row = connection.execute(
        """
        SELECT headword, leo_offset, page_span
        FROM index_entries
        WHERE normalized_headword = ?
          AND has_decoded_entry = 0
        ORDER BY leo_offset ASC
        LIMIT 1
        """,
        (normalized_query,),
    ).fetchone()

    if row is None:
        return None

    return {
        "headword": str(row["headword"]),
        "leo_offset": int(row["leo_offset"]),
        "page_span": int(row["page_span"]),
    }


def build_page_window(page: int, total_pages: int, radius: int = 2) -> list[int]:
    start = max(1, page - radius)
    end = min(total_pages, page + radius)
    return list(range(start, end + 1))


def build_page_url(dictionary_id: str, query: str, page: int) -> str:
    return "/?" + urlencode(
        {
            "dict": dictionary_id,
            "q": query,
            "page": page,
        }
    )


def build_dictionary_url(dictionary_id: str, query: str = "") -> str:
    params: dict[str, str] = {"dict": dictionary_id}
    if query:
        params["q"] = query
    return "/?" + urlencode(params)


def render_gloss_html(gloss: str) -> Markup:
    html_parts: list[str] = []
    rest = gloss

    marker_match = GLOSS_MARKER_RE.match(gloss)
    if marker_match:
        html_parts.append(
            '<span class="gloss-marker">'
            + html.escape(marker_match.group(1))
            + "</span> "
        )
        rest = gloss[marker_match.end() :]

    parts = GLOSS_TOKEN_RE.split(rest)
    if not parts:
        return Markup("".join(html_parts) + html.escape(rest))

    for part in parts:
        if not part:
            continue
        escaped = html.escape(part)
        if part.startswith("[") and part.endswith("]"):
            html_parts.append(f'<span class="gloss-note">{escaped}</span>')
        elif part.startswith("<") and part.endswith(">"):
            html_parts.append(f'<span class="gloss-label">{escaped}</span>')
        elif GRAMMAR_TOKEN_RE.match(part.strip()):
            html_parts.append(f'<span class="gloss-grammar">{escaped}</span>')
        else:
            html_parts.append(escaped)

    return Markup("".join(html_parts))
