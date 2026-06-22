from __future__ import annotations

import re

CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
PAGE_NUMBER_RE = re.compile(r"^\s*(page\s+\d+|\d+\s*/\s*\d+|\d+)\s*$", re.IGNORECASE)
BULLET_RE = re.compile(r"^[\s>*\-]*[•◦▪●▪■]+\s*", re.MULTILINE)
WHITESPACE_RE = re.compile(r"[ \t]+")
EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")
HYPHENATED_LINEBREAK_RE = re.compile(r"(\w)-\n(\w)")


def clean_text(text: str) -> str:
    """Normalize extracted page text before chunking."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = HYPHENATED_LINEBREAK_RE.sub(r"\1\2", normalized)
    normalized = CONTROL_CHARS_RE.sub("", normalized)
    normalized = normalized.replace("\u00a0", " ")
    normalized = BULLET_RE.sub("- ", normalized)

    lines = [line.strip() for line in normalized.split("\n")]
    filtered_lines = [line for line in lines if not PAGE_NUMBER_RE.match(line)]

    collapsed = "\n".join(filtered_lines)
    collapsed = WHITESPACE_RE.sub(" ", collapsed)
    collapsed = re.sub(r"\n +", "\n", collapsed)
    collapsed = re.sub(r" +\n", "\n", collapsed)
    collapsed = EXCESS_NEWLINES_RE.sub("\n\n", collapsed)
    return collapsed.strip()

