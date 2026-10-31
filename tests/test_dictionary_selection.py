from __future__ import annotations

from fastapi.testclient import TestClient

from dictionary.app import DICTIONARY_COOKIE, app
from dictionary.search import build_dictionary_url, build_page_url


def test_selected_dictionary_persists_for_later_visits() -> None:
    client = TestClient(app)

    selected = client.get("/?dict=en-es")

    assert selected.status_code == 200
    assert selected.cookies[DICTIONARY_COOKIE] == "en-es"

    revisited = client.get("/")

    assert revisited.status_code == 200
    assert "<title>Diccionario inglés-español</title>" in revisited.text
    assert "Inglés → español" in revisited.text


def test_invalid_dictionary_does_not_replace_saved_selection() -> None:
    client = TestClient(app)
    client.cookies.set(DICTIONARY_COOKIE, "es-en")

    response = client.get("/?dict=unknown")

    assert response.status_code == 200
    assert DICTIONARY_COOKIE not in response.cookies
    assert "Español → inglés" in response.text


def test_old_url_redirects_to_encoded_path_and_keeps_page() -> None:
    client = TestClient(app)
    response = client.get("/", params={"dict": "es-en", "q": "niño / niña", "page": 3}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/es-en/ni%C3%B1o%20%2F%20ni%C3%B1a?page=3"
    assert client.get(response.headers["location"]).status_code == 200


def test_canonical_dictionary_paths_and_link_builders() -> None:
    client = TestClient(app)
    assert client.get("/es-en").status_code == 200
    assert client.get("/es-en/casa").status_code == 200
    assert client.get("/no-existe/casa").status_code == 404
    assert build_dictionary_url("es-en", "niño azul") == "/es-en/ni%C3%B1o%20azul"
    assert build_page_url("es-en", "casa", 1) == "/es-en/casa"
    assert build_page_url("es-en", "casa", 2) == "/es-en/casa?page=2"
