from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


PROMPT_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"developer\s+message", re.IGNORECASE),
    re.compile(r"<\/?script\b", re.IGNORECASE),
    re.compile(r"<\/?(system|assistant|user)\b", re.IGNORECASE),
)

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"eyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9._-]{10,}\.[a-zA-Z0-9._-]{10,}"),
)

CHUNK_CITATION_PATTERN = re.compile(r"\[chunk:(\d+)\]", re.IGNORECASE)

# Injection markers that may appear *inside* retrieved document chunks (a poisoned document).
# We neutralize them defensively before the chunk text is placed in a prompt. The design already
# makes a successful injection harmless (the LLM has no authority), but per brief §12c we also
# strip the obvious markers so they cannot influence answer generation.
CHUNK_INJECTION_PATTERNS = (
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"system\s+prompt", re.IGNORECASE),
    re.compile(r"developer\s+message", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\b", re.IGNORECASE),
    re.compile(r"</?(system|assistant|user)\b", re.IGNORECASE),
)

# PII patterns: fields the requester may not be entitled to are masked before reaching the LLM.
EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_PATTERN = re.compile(r"\b(?:\+?\d[\d\s().-]{7,}\d)\b")
SSN_LIKE_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


@dataclass(slots=True)
class GuardrailViolation(Exception):
    reason: str
    stage: str = "input"
    status_code: int = 400

    def __str__(self) -> str:
        return self.reason


def input_guard(text: str, *, max_length: int = 600) -> str:
    normalized = " ".join(text.split()).strip()
    if not normalized:
        raise GuardrailViolation("empty_query", stage="input", status_code=422)
    if len(normalized) > max_length:
        raise GuardrailViolation("query_too_long", stage="input", status_code=422)
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(normalized):
            raise GuardrailViolation("prompt_injection_pattern", stage="input", status_code=400)
    return normalized


def contains_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def sanitize_chunk_text(text: str) -> str:
    """Neutralize injection markers inside retrieved document chunks (brief §12c).

    Defense in depth: the architecture already strips the LLM of authority, but a poisoned
    document should not be able to inject instructions into answer generation either. We replace
    recognized injection markers with a neutral placeholder rather than dropping content, so the
    chunk text stays readable as data.
    """
    cleaned = text or ""
    for pattern in CHUNK_INJECTION_PATTERNS:
        cleaned = pattern.sub("[removed-instruction]", cleaned)
    return cleaned


def redact_pii(text: str) -> str:
    """Mask PII (emails, phone numbers, SSN-like ids) in free text before it reaches the LLM.

    Used for content the requester is not entitled to see in raw form (brief §12d / FR-019).
    """
    redacted = text or ""
    redacted = EMAIL_PATTERN.sub("[redacted-email]", redacted)
    redacted = SSN_LIKE_PATTERN.sub("[redacted-id]", redacted)
    redacted = PHONE_PATTERN.sub("[redacted-phone]", redacted)
    return redacted


def extract_chunk_citation_ids(markdown: str) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for match in CHUNK_CITATION_PATTERN.finditer(markdown):
        chunk_id = int(match.group(1))
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        ordered.append(chunk_id)
    return ordered


def output_guard(
    payload: dict[str, Any],
    *,
    mode: str,
    retrieved_chunk_ids: set[int] | None = None,
) -> dict[str, Any]:
    answer_markdown = str(payload.get("answer_markdown") or "")
    if contains_secret(answer_markdown):
        raise GuardrailViolation("secret_pattern_detected", stage="output", status_code=502)

    if mode != "rag":
        return payload

    if bool(payload.get("refused")):
        return payload

    citation_ids = extract_chunk_citation_ids(answer_markdown)
    if not citation_ids:
        raise GuardrailViolation("missing_citations", stage="output", status_code=502)

    if retrieved_chunk_ids is not None:
        invalid_ids = [chunk_id for chunk_id in citation_ids if chunk_id not in retrieved_chunk_ids]
        if invalid_ids:
            raise GuardrailViolation("invalid_citations", stage="output", status_code=502)

    return payload
