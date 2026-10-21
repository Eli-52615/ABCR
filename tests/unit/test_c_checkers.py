import pytest
from abcr.eval.deterministic.checkers import (
    check_keywords_existence,
    check_keywords_forbidden,
    check_keyword_frequency,
    check_length_words,
    check_length_sentences,
    check_length_paragraphs,
    check_format_json,
    check_format_title,
    check_format_bullets,
    check_case_capital,
    check_case_lowercase,
    check_postscript,
    check_end_phrase,
    check_quotation,
)


class TestKeywordsExistence:
    def test_all_present(self):
        ok, _ = check_keywords_existence("Apple pie and Banana split", keywords=["apple", "banana"])
        assert ok

    def test_missing_one(self):
        ok, detail = check_keywords_existence("Apple pie only", keywords=["apple", "banana"])
        assert not ok
        assert "banana" in detail

    def test_word_boundary(self):
        ok, _ = check_keywords_existence("application is running", keywords=["app"])
        assert not ok


class TestKeywordsForbidden:
    def test_none_found(self):
        ok, _ = check_keywords_forbidden("A lovely day", forbidden_words=["hate", "ugly"])
        assert ok

    def test_found(self):
        ok, _ = check_keywords_forbidden("I hate this", forbidden_words=["hate", "ugly"])
        assert not ok

    def test_word_boundary(self):
        ok, _ = check_keywords_forbidden("therapist is helpful", forbidden_words=["the"])
        assert ok


class TestKeywordFrequency:
    def test_at_least_pass(self):
        ok, _ = check_keyword_frequency("the cat the dog the bird", keyword="the", frequency=3, relation="at least")
        assert ok

    def test_at_least_fail(self):
        ok, _ = check_keyword_frequency("the cat and dog", keyword="the", frequency=3, relation="at least")
        assert not ok

    def test_exactly(self):
        ok, _ = check_keyword_frequency("hello world hello", keyword="hello", frequency=2, relation="exactly")
        assert ok

    def test_at_most(self):
        ok, _ = check_keyword_frequency("one two one two one", keyword="one", frequency=2, relation="at most")
        assert not ok


class TestLengthWords:
    def test_at_least_pass(self):
        ok, _ = check_length_words("one two three four five", num_words=5, relation="at least")
        assert ok

    def test_at_least_fail(self):
        ok, _ = check_length_words("one two", num_words=5, relation="at least")
        assert not ok

    def test_less_than(self):
        ok, _ = check_length_words("one two three", num_words=5, relation="less than")
        assert ok


class TestLengthSentences:
    def test_two_sentences(self):
        ok, _ = check_length_sentences("First. Second.", num_sentences=2, relation="at least")
        assert ok

    def test_one_sentence_fail(self):
        ok, _ = check_length_sentences("Just one sentence.", num_sentences=2, relation="at least")
        assert not ok

    def test_question_mark(self):
        ok, _ = check_length_sentences("What? Why? How?", num_sentences=3, relation="at least")
        assert ok


class TestLengthParagraphs:
    def test_exact_match(self):
        ok, _ = check_length_paragraphs("Para one.\n\nPara two.", num_paragraphs=2)
        assert ok

    def test_too_few(self):
        ok, _ = check_length_paragraphs("Single paragraph.", num_paragraphs=2)
        assert not ok

    def test_three_paragraphs(self):
        ok, _ = check_length_paragraphs("P1.\n\nP2.\n\nP3.", num_paragraphs=3)
        assert ok


class TestFormatJson:
    def test_valid(self):
        ok, _ = check_format_json('  {"key": "value"}  ')
        assert ok

    def test_invalid(self):
        ok, _ = check_format_json("not json at all")
        assert not ok

    def test_array(self):
        ok, _ = check_format_json('[1, 2, 3]')
        assert ok


class TestFormatTitle:
    def test_present(self):
        ok, _ = check_format_title("<<My Title>>\nContent")
        assert ok

    def test_absent(self):
        ok, _ = check_format_title("No title here")
        assert not ok

    def test_single_angle(self):
        ok, _ = check_format_title("<Not a title>")
        assert not ok


class TestFormatBullets:
    def test_exact_count(self):
        ok, _ = check_format_bullets("* one\n* two\n* three", num_bullets=3)
        assert ok

    def test_wrong_count(self):
        ok, _ = check_format_bullets("* one\n* two", num_bullets=3)
        assert not ok

    def test_dash_not_counted(self):
        ok, _ = check_format_bullets("- one\n- two\n- three", num_bullets=3)
        assert not ok


class TestCaseCapital:
    def test_all_upper(self):
        ok, _ = check_case_capital("HELLO WORLD! 123")
        assert ok

    def test_mixed(self):
        ok, _ = check_case_capital("Hello World")
        assert not ok

    def test_no_alpha(self):
        ok, _ = check_case_capital("123 !@#")
        assert ok


class TestCaseLowercase:
    def test_all_lower(self):
        ok, _ = check_case_lowercase("hello world 123")
        assert ok

    def test_has_upper(self):
        ok, _ = check_case_lowercase("Hello world")
        assert not ok

    def test_no_alpha(self):
        ok, _ = check_case_lowercase("123 !@#")
        assert ok


class TestPostscript:
    def test_present(self):
        ok, _ = check_postscript("Content.\nP.S. extra", postscript_marker="P.S.")
        assert ok

    def test_absent(self):
        ok, _ = check_postscript("Content only.", postscript_marker="P.S.")
        assert not ok

    def test_custom_marker(self):
        ok, _ = check_postscript("Note: PS - extra", postscript_marker="PS -")
        assert ok


class TestEndPhrase:
    def test_exact_end(self):
        ok, _ = check_end_phrase("Story text. The end.", end_phrase="The end.")
        assert ok

    def test_trailing_whitespace(self):
        ok, _ = check_end_phrase("Story text. The end.   ", end_phrase="The end.")
        assert ok

    def test_trailing_quote(self):
        ok, _ = check_end_phrase('Story text. The end."', end_phrase="The end.")
        assert ok

    def test_wrong_end(self):
        ok, _ = check_end_phrase("Story text. Not done yet.", end_phrase="The end.")
        assert not ok


class TestQuotation:
    def test_quoted(self):
        ok, _ = check_quotation('"Quoted text."')
        assert ok

    def test_not_quoted(self):
        ok, _ = check_quotation("Not quoted.")
        assert not ok

    def test_single_quotes_not_counted(self):
        ok, _ = check_quotation("'Single quoted.'")
        assert not ok
