from __future__ import annotations

from contextlib import closing
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dictionary.moliner import load_articles
from dictionary import damer
from dictionary.search import (
    DICTIONARIES,
    PAGE_LIMIT,
    build_dictionary_url,
    build_gloss_anchor,
    build_page_url,
    build_page_window,
    build_sense_anchor,
    database_available,
    get_autocomplete_suggestions,
    get_dictionary,
    get_random_examples,
    load_stats,
    lookup_linkable_terms,
    normalize_for_search,
    open_dictionary_database,
    render_gloss_html,
    search_entries,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DICTIONARY_COOKIE = "dictionary_id"
DICTIONARY_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
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


@app.get("/", response_class=HTMLResponse, response_model=None)
def homepage(
    request: Request,
    dict: str | None = None,
    q: str = "",
    page: int = 1,
) -> HTMLResponse | RedirectResponse:
    if (dict in DICTIONARIES or q.strip()) and ("dict" in request.query_params or "q" in request.query_params):
        selected = get_dictionary(dict if dict in DICTIONARIES else request.cookies.get(DICTIONARY_COOKIE))
        return RedirectResponse(build_page_url(selected.id, q.strip(), max(1, page)), status_code=302)
    return render_homepage(request, dict, q, page)


def render_homepage(request: Request, dict: str | None, q: str, page: int) -> HTMLResponse:
    selected_dictionary_id = dict if dict in DICTIONARIES else None
    saved_dictionary_id = request.cookies.get(DICTIONARY_COOKIE)
    dictionary = get_dictionary(selected_dictionary_id or saved_dictionary_id)
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

    if dictionary.id == "damer":
        if query:
            try:
                article = damer.get_article(query)
                if article:
                    results = [{"headword": query, "damer_entries": damer.decode_article(article)["entries"]}]
                    total_results = total_pages = displayed_result_count = 1
            except Exception:
                error = "No se pudo consultar el Diccionario de americanismos. Intentá nuevamente."
    elif not database_available(dictionary):
        error = (
            "No encuentro la base de datos en "
            f"{dictionary.database_path}. Ejecutá el importador en Python antes "
            "de abrir el sitio."
        )
    else:
        try:
            with closing(open_dictionary_database(dictionary)) as connection:
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
                    if dictionary.id == "moliner":
                        load_articles(connection, results)
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
    response = templates.TemplateResponse(
        request=request,
        name="index.html",
        context=context,
    )
    if selected_dictionary_id:
        response.set_cookie(
            DICTIONARY_COOKIE,
            selected_dictionary_id,
            max_age=DICTIONARY_COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
    return response


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
    if dictionary.id == "damer":
        return JSONResponse({"suggestions": damer.suggestions(query)})
    if not database_available(dictionary):
        return JSONResponse({"suggestions": []}, status_code=503)

    with closing(open_dictionary_database(dictionary)) as connection:
        suggestions = get_autocomplete_suggestions(connection, normalized_query)
    return JSONResponse({"suggestions": suggestions})


@app.post("/api/linkable-terms", response_class=JSONResponse)
def linkable_terms(
    request: Request,
    dict: str = "de-es",
    terms: list[str] = Body(default=[]),
) -> JSONResponse:
    dictionary = get_dictionary(dict)

    if dictionary.id == "damer":
        return JSONResponse({"results": {}})

    if not database_available(dictionary):
        return JSONResponse(
            {
                "results": {},
                "error": "database_missing",
            },
            status_code=503,
        )

    with closing(open_dictionary_database(dictionary)) as connection:
        payload = lookup_linkable_terms(connection, dictionary.id, terms)
    return JSONResponse({"results": payload})


@app.get("/{dictionary_id}", response_class=HTMLResponse)
@app.get("/{dictionary_id}/{term:path}", response_class=HTMLResponse)
def dictionary_page(request: Request, dictionary_id: str, term: str = "", page: int = 1) -> HTMLResponse:
    if dictionary_id not in DICTIONARIES:
        raise HTTPException(status_code=404, detail="Diccionario no encontrado")
    return render_homepage(request, dictionary_id, term, page)
