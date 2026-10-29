"""Render DUE XML as escaped HTML, preserving its structure and references."""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from urllib.parse import urlencode

from markupsafe import Markup

BLOCK_TAGS = {
    "ENTRADA": "div",
    "VOZ": "div",
    "ACEPCIONES": "div",
    "ACEPCION": "div",
    "SUB-ACEPCION": "div",
    "GRUPO-HOMOGENEO": "div",
    "EXPRESIONES-PLURIVERBALES": "section",
    "EXPRESION": "div",
    "P": "p",
    "CATALOGO": "div",
    "FORMAS-DE-EXPRESION": "div",
    "NOTAS-USO": "div",
    "NOTA-FINAL": "div",
    "INTRODUCCION": "div",
}


def plain_text(node: ET.Element) -> str:
    return "".join(node.itertext()).strip()


def render_xml(node: ET.Element, targets: Mapping[str, str]) -> str:
    if node.tag == "BR":
        return "<br>"
    body = html.escape(node.text or "") + "".join(
        render_xml(child, targets) + html.escape(child.tail or "") for child in node
    )
    tag = BLOCK_TAGS.get(node.tag, "span")
    classes = ["moliner-" + node.tag.lower()]
    if node.tag == "FUENTE":
        for key in (
            "cursiva",
            "redonda",
            "sup",
            "sub",
            "negrita",
            "versalita",
            "ordenatriz",
        ):
            if node.get(key) == "1":
                classes.append("moliner-" + key)
        if node.get("face"):
            classes.append("moliner-font-" + node.get("face"))
    attributes = ' class="' + html.escape(" ".join(classes), quote=True) + '"'
    if node.get("id"):
        attributes += (
            ' id="' + html.escape("moliner-" + node.get("id"), quote=True) + '"'
        )
    target = node.get("id-ref")
    if node.tag == "REMISION" and target in targets:
        tag = "a"
        url = (
            "/?"
            + urlencode({"dict": "moliner", "q": targets[target]})
            + "#moliner-"
            + target
        )
        attributes += ' href="' + html.escape(url, quote=True) + '"'
    return f"<{tag}{attributes}>{body}</{tag}>"


def render_article(entry_xml: str, targets: Mapping[str, str]) -> tuple[Markup, Markup]:
    root = ET.fromstring(entry_xml)
    voice = root.find("VOZ")
    if voice is None or voice.find("LEMA") is None:
        raise ValueError("DUE article has no lemma")
    lemma = voice.find("LEMA")
    title = render_xml(lemma, targets)
    # The lemma is displayed in the card heading; retain any following text.
    tail = lemma.tail or ""
    voice.remove(lemma)
    voice.text = (voice.text or "") + tail
    return Markup(title), Markup(render_xml(root, targets))


def load_articles(connection, entries: list[dict]) -> None:
    if not entries:
        return
    placeholders = ",".join("?" for _ in entries)
    rows = connection.execute(
        f"SELECT entry_id, entry_xml FROM articles WHERE entry_id IN ({placeholders})",
        [entry["id"] for entry in entries],
    ).fetchall()
    articles = {row["entry_id"]: row["entry_xml"] for row in rows}
    reference_ids = {
        node.get("id-ref")
        for xml in articles.values()
        for node in ET.fromstring(xml).iter("REMISION")
        if node.get("id-ref")
    }
    targets = {}
    if reference_ids:
        placeholders = ",".join("?" for _ in reference_ids)
        targets = {
            row["xml_id"]: row["headword"]
            for row in connection.execute(
                f"""SELECT x.xml_id, e.headword FROM xml_ids x
                    JOIN entries e ON e.id = x.entry_id WHERE x.xml_id IN ({placeholders})""",
                list(reference_ids),
            ).fetchall()
        }
    for entry in entries:
        entry["title_html"], entry["article_html"] = render_article(
            articles[entry["id"]], targets
        )
