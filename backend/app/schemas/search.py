from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=600)
    analyze: bool = False


class SearchStatusLine(BaseModel):
    model: str
    retrieval: str
    reranked: bool
    n_retrieved: int
    k_cited: int
    latency_ms: int


class SearchResultItem(BaseModel):
    chunk_id: int
    document_id: int
    doc_code: str
    title: str
    page: int
    snippet: str
    score: float


class CitationItem(BaseModel):
    chunk_id: int
    doc_code: str
    page: int


class SourceItem(BaseModel):
    chunk_id: int
    document_id: int | None = None  # None for synthetic app-support corpus chunks
    doc_code: str
    title: str
    page: int
    cited: bool
    text: str


class SearchRetrievalResponse(BaseModel):
    mode: str = "retrieval"
    results: list[SearchResultItem]
    status_line: SearchStatusLine


class SearchAnswerResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    mode: str = "answer"
    answer_markdown: str
    citations: list[CitationItem]
    sources: list[SourceItem]
    refused: bool
    status_line: SearchStatusLine
