from __future__ import annotations

from dataclasses import dataclass
import re

from ingestion.extract import ExtractedPage

WORD_RE = re.compile(r"\S+")


@dataclass(slots=True)
class ChunkRecord:
    doc_code: str
    title: str
    doc_type: str
    page: int
    chunk_index: int
    text: str


@dataclass(slots=True)
class TextUnit:
    text: str
    page: int


def estimate_tokens(text: str) -> int:
    return len(WORD_RE.findall(text))


def tail_tokens(text: str, token_count: int) -> str:
    words = WORD_RE.findall(text)
    if token_count <= 0 or len(words) <= token_count:
        return text.strip()
    return " ".join(words[-token_count:]).strip()


def _split_large_unit(unit: TextUnit, max_tokens: int, overlap_tokens: int) -> list[TextUnit]:
    words = WORD_RE.findall(unit.text)
    if len(words) <= max_tokens:
        return [unit]

    chunks: list[TextUnit] = []
    step = max(max_tokens - overlap_tokens, 1)
    for start in range(0, len(words), step):
        part = words[start : start + max_tokens]
        if not part:
            continue
        chunks.append(TextUnit(text=" ".join(part), page=unit.page))
        if start + max_tokens >= len(words):
            break
    return chunks


def _page_paragraph_units(pages: list[ExtractedPage], max_tokens: int, overlap_tokens: int) -> list[TextUnit]:
    units: list[TextUnit] = []
    for page in pages:
        paragraphs = [paragraph.strip() for paragraph in page.text.split("\n\n") if paragraph.strip()]
        for paragraph in paragraphs:
            units.extend(_split_large_unit(TextUnit(text=paragraph, page=page.page_number), max_tokens, overlap_tokens))
    return units


def chunk_document(
    pages: list[ExtractedPage],
    *,
    doc_code: str,
    title: str,
    doc_type: str,
    target_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[ChunkRecord]:
    units = _page_paragraph_units(pages, target_tokens, overlap_tokens)
    if not units:
        return []

    chunks: list[ChunkRecord] = []
    current_units: list[TextUnit] = []
    current_tokens = 0

    def flush_chunk(chunk_index: int) -> tuple[list[TextUnit], int]:
        chunk_text = "\n\n".join(unit.text for unit in current_units if unit.text.strip()).strip()
        if not chunk_text:
            return [], 0
        page = current_units[0].page
        chunks.append(
            ChunkRecord(
                doc_code=doc_code,
                title=title,
                doc_type=doc_type,
                page=page,
                chunk_index=chunk_index,
                text=chunk_text,
            )
        )
        overlap_text = tail_tokens(chunk_text, overlap_tokens)
        if not overlap_text:
            return [], 0
        overlap_page = current_units[-1].page
        return [TextUnit(text=overlap_text, page=overlap_page)], estimate_tokens(overlap_text)

    for unit in units:
        unit_tokens = estimate_tokens(unit.text)
        if current_units and current_tokens + unit_tokens > target_tokens:
            current_units, current_tokens = flush_chunk(len(chunks))
        current_units.append(unit)
        current_tokens += unit_tokens

    if current_units:
        flush_chunk(len(chunks))

    return chunks

