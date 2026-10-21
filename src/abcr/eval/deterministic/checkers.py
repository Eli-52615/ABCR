# Word split: \S+ tokens. Sentence split: split on [.!?] followed by optional quotes/parens then space or end.
import re
import json
from typing import Tuple


def check_keywords_existence(text: str, *, keywords: list[str]) -> Tuple[bool, str]:
    text_lower = text.lower()
    missing = []
    for kw in keywords:
        pattern = re.compile(r'\b' + re.escape(kw.lower()) + r'\b')
        if not pattern.search(text_lower):
            missing.append(kw)
    if missing:
        return False, f"missing keywords: {missing}"
    return True, "all keywords present"


def check_keywords_forbidden(text: str, *, forbidden_words: list[str]) -> Tuple[bool, str]:
    text_lower = text.lower()
    found = []
    for fw in forbidden_words:
        pattern = re.compile(r'\b' + re.escape(fw.lower()) + r'\b')
        if pattern.search(text_lower):
            found.append(fw)
    if found:
        return False, f"forbidden words found: {found}"
    return True, "no forbidden words found"


def check_keyword_frequency(text: str, *, keyword: str, frequency: int, relation: str) -> Tuple[bool, str]:
    pattern = re.compile(r'\b' + re.escape(keyword.lower()) + r'\b')
    count = len(pattern.findall(text.lower()))
    passed = _check_relation(count, frequency, relation)
    return passed, f"keyword '{keyword}' appears {count} times (required: {relation} {frequency})"


def check_length_words(text: str, *, num_words: int, relation: str) -> Tuple[bool, str]:
    words = re.findall(r'\S+', text)
    count = len(words)
    passed = _check_relation(count, num_words, relation)
    return passed, f"word count: {count} (required: {relation} {num_words})"


def check_length_sentences(text: str, *, num_sentences: int, relation: str) -> Tuple[bool, str]:
    count = _count_sentences(text)
    passed = _check_relation(count, num_sentences, relation)
    return passed, f"sentence count: {count} (required: {relation} {num_sentences})"


def check_length_paragraphs(text: str, *, num_paragraphs: int) -> Tuple[bool, str]:
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n', text.strip()) if p.strip()]
    count = len(paragraphs)
    passed = count == num_paragraphs
    return passed, f"paragraph count: {count} (required: exactly {num_paragraphs})"


def check_format_json(text: str) -> Tuple[bool, str]:
    try:
        json.loads(text.strip())
        return True, "valid JSON"
    except (json.JSONDecodeError, ValueError) as e:
        return False, f"invalid JSON: {e}"


def check_format_title(text: str) -> Tuple[bool, str]:
    pattern = re.compile(r'<<[^>]+>>')
    if pattern.search(text):
        return True, "title found"
    return False, "no <<title>> found"


def check_format_bullets(text: str, *, num_bullets: int) -> Tuple[bool, str]:
    bullet_lines = [line for line in text.split('\n') if line.strip().startswith('* ')]
    count = len(bullet_lines)
    passed = count == num_bullets
    return passed, f"bullet count: {count} (required: exactly {num_bullets})"


def check_case_capital(text: str) -> Tuple[bool, str]:
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return True, "no alphabetic characters"
    all_upper = all(c.isupper() for c in alpha_chars)
    return all_upper, "all uppercase" if all_upper else "not all uppercase"


def check_case_lowercase(text: str) -> Tuple[bool, str]:
    alpha_chars = [c for c in text if c.isalpha()]
    if not alpha_chars:
        return True, "no alphabetic characters"
    all_lower = all(c.islower() for c in alpha_chars)
    return all_lower, "all lowercase" if all_lower else "not all lowercase"


def check_postscript(text: str, *, postscript_marker: str) -> Tuple[bool, str]:
    if postscript_marker in text:
        return True, f"postscript marker '{postscript_marker}' found"
    return False, f"postscript marker '{postscript_marker}' not found"


def check_end_phrase(text: str, *, end_phrase: str) -> Tuple[bool, str]:
    stripped = text.rstrip()
    stripped = stripped.rstrip('"\'')
    stripped = stripped.rstrip()
    if stripped.endswith(end_phrase):
        return True, f"ends with '{end_phrase}'"
    return False, f"does not end with '{end_phrase}'"


def check_quotation(text: str) -> Tuple[bool, str]:
    stripped = text.strip()
    if stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
        return True, "wrapped in double quotes"
    return False, "not wrapped in double quotes"


def _check_relation(actual: int, target: int, relation: str) -> bool:
    relation_lower = relation.lower().strip()
    if relation_lower == "at least":
        return actual >= target
    elif relation_lower == "at most":
        return actual <= target
    elif relation_lower == "exactly":
        return actual == target
    elif relation_lower == "less than":
        return actual < target
    elif relation_lower == "more than":
        return actual > target
    raise ValueError(f"unknown relation: {relation}")


def _count_sentences(text: str) -> int:
    if not text.strip():
        return 0
    parts = re.split(r'(?<=[.!?])[\"\'\)]*(?:\s|$)', text.strip())
    sentences = [p.strip() for p in parts if p.strip()]
    return len(sentences)
