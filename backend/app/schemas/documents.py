from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DocumentQueuedResponse(BaseModel):
    document_id: int
    embedding_status: Literal["pending"]


class DocumentListItem(BaseModel):
    id: int
    doc_code: str
    title: str
    doc_type: str
    embedding_status: str
    chunk_count: int | None
    uploaded_at: datetime
    processed_at: datetime | None
    error_message: str | None


class DocumentStatusResponse(BaseModel):
    document_id: int
    embedding_status: str
    chunk_count: int | None
    error_message: str | None


class DocumentPreviewChunkResponse(BaseModel):
    document_id: int
    doc_code: str
    title: str
    page: int
    chunk_id: int
    chunk_index: int
    text: str
