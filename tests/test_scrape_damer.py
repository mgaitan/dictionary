import pytest

from tools.scrape_damer import parse_page


def test_parse_page_keeps_all_articles_and_follows_wheel():
    page = """<entry id="1">uno</entry><entry id="2">dos</entry>
    <ul class='rueda'><li><a href='/damer/z'>z</a></li>
    <li><b>a</b></li><li><a href='/damer/a%C3%A1'>aá</a></li></ul>"""
    articles, following = parse_page(page, "a")
    assert articles == '<entry id="1">uno</entry>\n<entry id="2">dos</entry>'
    assert following == "aá"


def test_parse_page_rejects_missing_article():
    with pytest.raises(ValueError):
        parse_page("<html></html>", "a")
