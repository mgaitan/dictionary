from __future__ import annotations

from contextlib import closing
from pathlib import Path

from fastapi import Body, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dictionary.search import (
    DICTIONARIES,
    PAGE_LIMIT,
    build_dictionary_url,
    build_gloss_anchor,
    build_page_url,
    build_page_window,
    build_sense_anchor,
    get_autocomplete_suggestions,
    get_dictionary,
    get_random_examples,
    load_stats,
    lookup_linkable_terms,
    normalize_for_search,
    open_database,
    render_gloss_html,
    search_entries,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters["render_gloss_html"] = render_gloss_html
templates.env.globals["build_page_url"] = build_page_url
templates.env.globals["build_dictionary_url"] = build_dictionary_url
templates.env.globals["build_page_window"] = build_page_window
templates.env.globals["build_sense_anchor"] = build_sense_anchor
templates.env.globals["build_gloss_anchor"] = build_gloss_anchor


def static_asset_url(request: Request, path: str) -> str:
    asset_path = STATIC_DIR / path
    version = str(int(asset_path.stat().st_mtime)) if asset_path.is_file() else "0"
    return str(request.url_for("static", path=path).include_query_params(v=version))


templates.env.globals["static_asset_url"] = static_asset_url

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
    random_examples = get_random_examples(dictionary)
    random_placeholder = "Ej. " + ", ".join(random_examples)

    error = None
    results: list[dict[str, object]] = []
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
                    displayed_result_count = len(results)
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
        "total_results": total_results,
        "total_pages": total_pages,
        "displayed_result_count": displayed_result_count,
        "error": error,
        "stats": stats,
        "random_examples": random_examples,
        "random_placeholder": random_placeholder,
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


@app.get("/api/autocomplete", response_class=JSONResponse)
def autocomplete(
    request: Request,
    dict: str = "de-es",
    q: str = "",
) -> JSONResponse:
    query = q.strip()
    normalized_query = normalize_for_search(query)
    if not normalized_query:
        return JSONResponse({"suggestions": []})

    dictionary = get_dictionary(dict)
    if not dictionary.database_path.is_file():
        return JSONResponse({"suggestions": []}, status_code=503)

    with closing(open_database(dictionary.database_path)) as connection:
        suggestions = get_autocomplete_suggestions(connection, normalized_query)
    return JSONResponse({"suggestions": suggestions})


@app.post("/api/linkable-terms", response_class=JSONResponse)
def linkable_terms(
    request: Request,
    dict: str = "de-es",
    terms: list[str] = Body(default=[]),
) -> JSONResponse:
    dictionary = get_dictionary(dict)

    if not dictionary.database_path.is_file():
        return JSONResponse(
            {
                "results": {},
                "error": "database_missing",
            },
            status_code=503,
        )

    with closing(open_database(dictionary.database_path)) as connection:
        payload = lookup_linkable_terms(connection, dictionary.id, terms)
    return JSONResponse({"results": payload})
