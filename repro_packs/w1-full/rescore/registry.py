from typing import Any
from checkers import (
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

_REGISTRY: dict[str, Any] = {
    "keywords_existence": check_keywords_existence,
    "keywords_forbidden": check_keywords_forbidden,
    "keyword_frequency": check_keyword_frequency,
    "length_words": check_length_words,
    "length_sentences": check_length_sentences,
    "length_paragraphs": check_length_paragraphs,
    "format_json": check_format_json,
    "format_title": check_format_title,
    "format_bullets": check_format_bullets,
    "case_capital": check_case_capital,
    "case_lowercase": check_case_lowercase,
    "postscript": check_postscript,
    "end_phrase": check_end_phrase,
    "quotation": check_quotation,
}


def get_checker(name: str) -> Any:
    if name not in _REGISTRY:
        raise KeyError(f"unknown checker: {name}")
    return _REGISTRY[name]


def run_checks(text: str, checks: list[dict]) -> list[dict]:
    results = []
    for check in checks:
        name = check["name"]
        kwargs = check.get("kwargs", {})
        fn = get_checker(name)
        passed, detail = fn(text, **kwargs)
        results.append({"name": name, "pass": passed, "detail": detail})
    return results
