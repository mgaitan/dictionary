from __future__ import annotations

import json
import struct
import xml.etree.ElementTree as ET
import zlib
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dictionary.app import app
from dictionary.moliner import render_article
from dictionary.search import DICTIONARIES
from tools.build_moliner_database import build_database, search_terms
from tools.extract_moliner import Reader, decrypt_cfs, export_articles


def vint(value: int) -> bytes:
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    result.append(value)
    return bytes(result)


def lucene_string(value: str) -> bytes:
    return vint(len(value)) + value.encode()


def write_cfs(path: Path, articles: list[dict]) -> None:
    names = ["idEntrada", "lema", "idLema", "xmlLema", "xmlEntrada"]
    fnm = vint(len(names)) + b"".join(lucene_string(name) + b"\1" for name in names)
    fdx, fdt = bytearray(), bytearray()
    for article in articles:
        fdx.extend(struct.pack(">Q", len(fdt)))
        fdt.extend(vint(len(names)))
        for i, name in enumerate(names):
            value = zlib.compress(article[name].encode())
            fdt.extend(vint(i) + b"\5" + vint(len(value)) + value)
    parts = [("_test.fnm", fnm), ("_test.fdx", fdx), ("_test.fdt", fdt)]
    offset = 1 + sum(8 + len(lucene_string(name)) for name, _ in parts)
    directory = bytearray(vint(len(parts)))
    for name, content in parts:
        directory.extend(struct.pack(">Q", offset) + lucene_string(name))
        offset += len(content)
    path.write_bytes(directory + b"".join(content for _, content in parts))


@pytest.fixture
def moliner(tmp_path, monkeypatch):
    monkeypatch.delenv("MOLINER_DATABASE_URL", raising=False)
    articles = [
        {
            "idEntrada": "1",
            "idLema": "17",
            "lema": "abacá",
            "xmlLema": '<LEMA id="DUE_17">abacá</LEMA>',
            "xmlEntrada": '<ENTRADA id-entrada="1"><VOZ><LEMA id="DUE_17">abacá</LEMA><ETIMOLOGIA> (del tagalo)</ETIMOLOGIA></VOZ><ACEPCIONES><ACEPCION><CAT-GRAM>m.</CAT-GRAM> *Planta tropical. <EJEMPLOS>Una tela.</EJEMPLOS> Véase <REMISION id-ref="DUE_30">casa</REMISION>.</ACEPCION></ACEPCIONES></ENTRADA>',
        },
        {
            "idEntrada": "2",
            "idLema": "30",
            "lema": "casa",
            "xmlLema": '<LEMA id="DUE_30">casa</LEMA>',
            "xmlEntrada": '<ENTRADA id-entrada="2"><VOZ><LEMA id="DUE_30">casa</LEMA></VOZ><ACEPCIONES><ACEPCION>Edificio destinado a vivienda.</ACEPCION></ACEPCIONES><EXPRESIONES-PLURIVERBALES><EXPRESION><LEXIA id="DUE_31">c. de campo</LEXIA><ACEPCION>Casa en el campo.</ACEPCION></EXPRESION></EXPRESIONES-PLURIVERBALES></ENTRADA>',
        },
    ]
    source = tmp_path / "source.cfs"
    write_cfs(source, articles)
    export = tmp_path / "articles.jsonl"
    assert export_articles(source, export) == 2
    database = tmp_path / "moliner.sqlite"
    stats = build_database(export, database)
    assert stats["entries"] == 2 and stats["senses"] == 3
    monkeypatch.setitem(
        DICTIONARIES,
        "moliner",
        replace(DICTIONARIES["moliner"], database_path=database),
    )
    return TestClient(app), export, database


def test_extraction_and_website(moliner):
    client, export, _ = moliner
    original = json.loads(export.read_text().splitlines()[0])
    assert "*Planta tropical." in original["entry_xml"]
    assert original["lemma_id"] == "17"
    page = client.get("/", params={"dict": "moliner", "q": "abaca"})
    assert page.status_code == 200
    assert "Uso del español (María Moliner)" in page.text
    assert "*Planta tropical." in page.text and "Una tela." in page.text
    assert "(del tagalo)" in page.text
    assert 'href="/?dict=moliner&amp;q=casa#moliner-DUE_30"' in page.text
    assert 'class="moliner-ejemplos"' in page.text
    assert 'id="moliner-DUE_17"' in page.text
    assert client.get(
        "/api/autocomplete", params={"dict": "moliner", "q": "abac"}
    ).json() == {"suggestions": ["abacá"]}
    assert (
        "Edificio destinado"
        in client.get("/", params={"dict": "moliner", "q": "casa de campo"}).text
    )
    links = client.post(
        "/api/linkable-terms?dict=moliner", json=["abacá", "casa"]
    ).json()["results"]
    assert links["abaca"]["headword"] == "abacá"


def test_missing_database_and_pagination(moliner):
    client, _, database = moliner
    page = client.get("/", params={"dict": "moliner", "q": "casa", "page": 999})
    assert "Página 1 de 1" in page.text
    assert (
        "No encontré coincidencias"
        in client.get("/", params={"dict": "moliner", "q": "ausente"}).text
    )
    database.unlink()
    assert client.get("/api/autocomplete?dict=moliner&q=a").status_code == 503
    assert (
        client.post("/api/linkable-terms?dict=moliner", json=["casa"]).status_code
        == 503
    )
    assert "no pudo abrir" in client.get("/?dict=moliner").text


def test_rendering_escapes_text_and_untrusted_attributes():
    xml = '<ENTRADA><VOZ><LEMA id="DUE_1">a<FUENTE sup="1">1</FUENTE></LEMA></VOZ><ACEPCIONES><ACEPCION>&lt;script&gt;alert(1)&lt;/script&gt;<SCRIPT onclick="bad()">texto</SCRIPT><FUENTE cursiva="1" face="&quot; onmouseover=&quot;bad()">griego</FUENTE><REMISION id-ref="missing">sin destino</REMISION></ACEPCION></ACEPCIONES></ENTRADA>'
    title, body = render_article(xml, {})
    assert "moliner-sup" in title
    assert "&lt;script&gt;" in body
    assert "<SCRIPT" not in body and "<script" not in body
    assert ' onclick="' not in body and ' onmouseover="' not in body
    assert "sin destino" in body and "href=" not in body
    # HTML is XML-compatible here, so a second parser confirms attribute boundaries.
    ET.fromstring(str(body))


def test_rejects_truncated_or_invalid_lucene(tmp_path):
    with pytest.raises(ValueError, match="Truncated"):
        Reader(b"\x80").vint()
    with pytest.raises(ValueError, match="VInt"):
        Reader(b"\x80" * 5).vint()
    with pytest.raises(ValueError, match="encrypted"):
        decrypt_cfs(b"\0" * 20)
    source = tmp_path / "bad.cfs"
    write_cfs(
        source,
        [
            {
                name: "x"
                for name in ["idEntrada", "lema", "idLema", "xmlLema", "xmlEntrada"]
            }
        ],
    )
    source.write_bytes(source.read_bytes()[:-3])
    destination = tmp_path / "articles.jsonl"
    destination.write_text("keep previous export")
    with pytest.raises((ValueError, zlib.error)):
        export_articles(source, destination)
    assert destination.read_text() == "keep previous export"


def test_failed_import_preserves_previous_database(moliner):
    _, source, database = moliner
    before = database.read_bytes()
    source.write_text('{"entry_xml":"<ENTRADA/>","id":"1"}\n')
    with pytest.raises(ValueError, match="ID"):
        build_database(source, database)
    assert database.read_bytes() == before


def test_homonym_number_keeps_following_gender_suffix():
    root = ET.fromstring(
        '<ENTRADA><VOZ><LEMA>actor<FUENTE sup="1">1</FUENTE>, -a</LEMA></VOZ></ENTRADA>'
    )
    assert ("actor, -a", "variant") in search_terms(root, "actor 1, -a")


def test_turso_configuration_does_not_override_local_database(moliner, monkeypatch):
    client, _, _ = moliner
    monkeypatch.setenv("MOLINER_DATABASE_URL", "libsql://example.invalid")
    monkeypatch.setenv("MOLINER_AUTH_TOKEN", "test-token")
    response = client.get("/?dict=moliner&q=abaca")
    assert "*Planta tropical." in response.text
    assert "test-token" not in response.text
