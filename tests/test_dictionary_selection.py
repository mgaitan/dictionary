from __future__ import annotations

from fastapi.testclient import TestClient

from dictionary.app import DICTIONARY_COOKIE, app


def test_selected_dictionary_persists_for_later_visits() -> None:
    client = TestClient(app)

    selected = client.get("/?dict=en-es")

    assert selected.status_code == 200
    assert selected.cookies[DICTIONARY_COOKIE] == "en-es"

    revisited = client.get("/")

    assert revisited.status_code == 200
    assert "<title>Diccionario inglés-español</title>" in revisited.text
    assert "Inglés -&gt; español" in revisited.text


def test_invalid_dictionary_does_not_replace_saved_selection() -> None:
    client = TestClient(app)
    client.cookies.set(DICTIONARY_COOKIE, "es-en")

    response = client.get("/?dict=unknown")

    assert response.status_code == 200
    assert DICTIONARY_COOKIE not in response.cookies
    assert "Español -&gt; inglés" in response.text
