import pytest

from tools.discover_damer import wheel


def test_wheel_returns_following_keys_including_encoded_and_uppercase():
    page = """<ul class='rueda'><li><a href='/damer/z'>z</a></li>
    <li><b>a</b></li><li><a href='/damer/A'>A</a></li>
    <li><a href='/damer/a%C3%A1'>aá</a></li></ul>"""
    assert wheel(page, "a") == ["A", "aá"]


def test_wheel_rejects_missing_current_word():
    with pytest.raises(ValueError):
        wheel("<ul class='rueda'><li><b>x</b></li></ul>", "a")


def test_wheel_handles_alias_highlighted_as_another_word():
    page = "<ul class='rueda'><li><a href='/damer/ir'>ir</a></li><li><b>irse</b></li><li><a href='/damer/isla'>isla</a></li></ul>"
    assert wheel(page, "ir") == ["irse", "isla"]


def test_wheel_keeps_question_mark_in_key():
    page = "<ul class='rueda'><li><b>agutí</b></li><li><a href='/damer/¿ah?'>¿ah?</a></li></ul>"
    assert wheel(page, "agutí") == ["¿ah?"]


def test_wheel_handles_unescaped_apostrophe_in_href():
    page = "<ul class='rueda'><li><b>puzunque</b></li><li><a href=\"/damer/q'arachupa\">q'arachupa</a></li></ul>"
    assert wheel(page, "puzunque") == ["q'arachupa"]
