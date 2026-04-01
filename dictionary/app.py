from __future__ import annotations

from contextlib import closing
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dictionary.search import (
    DICTIONARIES,
    PAGE_LIMIT,
    build_dictionary_url,
    build_page_url,
    build_page_window,
    find_unresolved_index_entry,
    get_dictionary,
    load_stats,
    normalize_for_search,
    open_database,
    render_gloss_html,
    search_entries,
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["render_gloss_html"] = render_gloss_html
templates.env.globals["build_page_url"] = build_page_url
templates.env.globals["build_dictionary_url"] = build_dictionary_url
templates.env.globals["build_page_window"] = build_page_window

app = FastAPI(title="dictionary")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
def homepage(
    request: Request,
    dict: str = "de-es",
    q: str = "",
    page: int = 1,
) -> HTMLResponse:
    dictionary = get_dictionary(dict)
    query = q.strip()
    normalized_query = normalize_for_search(query)
    page = max(1, page)

    error = None
    results: list[dict[str, object]] = []
    fallback_index_entry: dict[str, object] | None = None
    total_results = 0
    total_pages = 0
    displayed_result_count = 0
    stats = {"entries": 0, "senses": 0}

    if not dictionary.database_path.is_file():
        error = (
            "No encuentro la base SQLite en "
            f"{dictionary.database_path}. Ejecutá el importador en Python antes "
            "de abrir el sitio."
        )
    else:
        try:
            with closing(open_database(dictionary.database_path)) as connection:
                stats = load_stats(connection)
                if normalized_query:
                    search = search_entries(
                        connection,
                        query=query,
                        normalized_query=normalized_query,
                        limit=PAGE_LIMIT,
                        page=page,
                    )
                    total_results = int(search["total"])
                    total_pages = max(1, (total_results + PAGE_LIMIT - 1) // PAGE_LIMIT)
                    page = min(page, total_pages)
                    if int(search["page"]) != page:
                        search = search_entries(
                            connection,
                            query=query,
                            normalized_query=normalized_query,
                            limit=PAGE_LIMIT,
                            page=page,
                        )
                    results = list(search["entries"])
                    fallback_index_entry = find_unresolved_index_entry(
                        connection,
                        normalized_query,
                        results,
                    )
                    displayed_result_count = len(results) + (
                        1 if fallback_index_entry is not None else 0
                    )
        except Exception as exc:  # pragma: no cover - surface error in UI
            error = str(exc)

    context = {
        "request": request,
        "dictionaries": DICTIONARIES,
        "dictionary_id": dictionary.id,
        "dictionary": dictionary,
        "query": query,
        "normalized_query": normalized_query,
        "page": page,
        "results": results,
        "fallback_index_entry": fallback_index_entry,
        "total_results": total_results,
        "total_pages": total_pages,
        "displayed_result_count": displayed_result_count,
        "error": error,
        "stats": stats,
    }
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context,
    )


@app.get("/healthz", response_class=JSONResponse)
def healthcheck() -> JSONResponse:
    payload = {
        "ok": True,
        "dictionaries": sorted(DICTIONARIES.keys()),
    }
    return JSONResponse(payload)
