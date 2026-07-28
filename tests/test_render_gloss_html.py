"""Tests for render_gloss_html and inline label expansion."""

from __future__ import annotations

from dictionary.search import LABEL_EXPANSIONS, _expand_label, render_gloss_html


class TestExpandLabel:
    def test_known_single_labels(self) -> None:
        assert _expand_label("V") == "Ornitología/Vogelkunde"
        assert _expand_label("pop") == "popular/coloquial"
        assert _expand_label("fam") == "familiar"
        assert _expand_label("fig") == "figurado"
        assert _expand_label("Mil") == "Militar"
        assert _expand_label("Med") == "Medicina"

    def test_case_insensitive_lookup(self) -> None:
        # "span" (lowercase) and "Span" both map to España
        assert _expand_label("span") == "España"
        assert _expand_label("Span") == "España"

    def test_composite_labels_both_known(self) -> None:
        result = _expand_label("Am fam")
        assert result == "América · familiar"

    def test_composite_labels_partial_known(self) -> None:
        # "auch" is known, "fig" is known
        result = _expand_label("auch fig")
        assert result is not None
        assert "también" in result
        assert "figurado" in result

    def test_composite_label_bes_dot(self) -> None:
        # Trailing punctuation stripped: "bes." → "bes"
        result = _expand_label("bes. Am")
        assert result is not None
        assert "especialmente" in result
        assert "América" in result

    def test_unknown_single_label(self) -> None:
        assert _expand_label("XYZ") is None
        assert _expand_label("unknown") is None

    def test_all_unknown_composite(self) -> None:
        # If none of the parts are known, return None
        assert _expand_label("XYZ ABC") is None

    def test_label_expansions_dict_populated(self) -> None:
        # Ensure the dict has a reasonable number of entries
        assert len(LABEL_EXPANSIONS) > 20


class TestRenderGlossHtml:
    def test_plain_text_unchanged(self) -> None:
        result = str(render_gloss_html("plain text"))
        assert result == "plain text"

    def test_known_label_gets_title(self) -> None:
        result = str(render_gloss_html("ein Kerl <pop> canalla"))
        assert 'class="gloss-label"' in result
        assert 'title="popular/coloquial"' in result
        assert "&lt;pop&gt;" in result

    def test_v_label_ornithology_title(self) -> None:
        result = str(render_gloss_html("Adler m <V> águila f"))
        assert 'title="Ornitología/Vogelkunde"' in result
        assert "&lt;V&gt;" in result

    def test_unknown_label_no_title(self) -> None:
        result = str(render_gloss_html("text <XYZ> more"))
        assert 'class="gloss-label"' in result
        assert "title=" not in result
        assert "&lt;XYZ&gt;" in result

    def test_composite_label_title(self) -> None:
        result = str(render_gloss_html("word <Am fam> translation"))
        assert 'title="América · familiar"' in result
        assert "&lt;Am fam&gt;" in result

    def test_note_brackets_unchanged(self) -> None:
        result = str(render_gloss_html("word [some note] more"))
        assert 'class="gloss-note"' in result
        assert "title=" not in result

    def test_grammar_token_unchanged(self) -> None:
        result = str(render_gloss_html("Adler m águila f"))
        assert 'class="gloss-grammar"' in result
        assert "title=" not in result

    def test_span_lowercase_gets_spain_title(self) -> None:
        # <span> in the data means "España" (Spain), not the HTML element
        result = str(render_gloss_html("in <span> in Spanien"))
        assert 'title="España"' in result
        assert "&lt;span&gt;" in result

    def test_returns_markup_type(self) -> None:
        from markupsafe import Markup

        result = render_gloss_html("test <pop> value")
        assert isinstance(result, Markup)

    def test_headword_stripped(self) -> None:
        result = str(render_gloss_html("Adler m <V> águila f", headword="Adler"))
        # Headword "Adler" at the start should be stripped
        assert not result.startswith("Adler")

    def test_gloss_marker_prefix(self) -> None:
        result = str(render_gloss_html("a) some sense <fam> text"))
        assert 'class="gloss-marker"' in result
        assert 'title="familiar"' in result
