from __future__ import annotations

from pathlib import Path
import hashlib
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from backend.app.config import get_settings
from backend.app.llm.client import embed_texts
from backend.app.db import session_scope
from backend.app.models import Chunk, Document
from backend.app.schema import bootstrap_schema
from ingestion.chunk import ChunkRecord, chunk_document
from ingestion.clean import clean_text
from ingestion.extract import ExtractedDocument, ExtractedPage, extract_document


@dataclass(slots=True)
class PipelineResult:
    document_id: int
    doc_code: str
    page_count: int
    chunk_count: int
    source_path: str


def infer_doc_type(source_path: Path) -> str:
    stem = source_path.stem.lower()
    if any(token in stem for token in ("policy", "handbook", "procedure")):
        return "policy"
    if any(token in stem for token in ("guide", "howto", "how-to", "faq", "help")):
        return "howto"
    return "reference"


def generate_doc_code(source_path: Path, doc_type: str) -> str:
    prefix = {"policy": "POL", "howto": "HOW", "reference": "DOC"}[doc_type]
    digest = hashlib.sha1(source_path.stem.encode("utf-8")).hexdigest()[:6].upper()
    return f"{prefix}-{digest}"


def normalize_pages(extracted: ExtractedDocument) -> list[ExtractedPage]:
    cleaned_pages = []
    for page in extracted.pages:
        cleaned_pages.append(
            ExtractedPage(
                page_number=page.page_number,
                text=clean_text(page.text),
                source_kind=page.source_kind,
            )
        )
    return cleaned_pages


def build_embeddings(texts: list[str]) -> list[list[float]]:
    return embed_texts(texts)


def _staged_source_path(source_path: Path, doc_code: str) -> Path:
    settings = get_settings()
    root = Path(settings.upload_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{doc_code}{source_path.suffix.lower()}"
    if source_path.resolve() != destination.resolve():
        shutil.copy2(source_path, destination)
    return destination


def _upsert_document(
    session: Session,
    *,
    document_id: int | None,
    doc_code: str,
    title: str,
    doc_type: str,
    source_path: str,
    page_count: int,
    uploaded_by_user_id: int,
) -> Document:
    if document_id is not None:
        document = session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document id {document_id} does not exist.")
        document.doc_code = doc_code
        document.title = title
        document.doc_type = doc_type
        document.source_path = source_path
        document.page_count = page_count
        document.error_message = None
        document.embedding_status = "processing"
        session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        session.flush()
        return document

    document = Document(
        doc_code=doc_code,
        title=title,
        doc_type=doc_type,
        source_path=source_path,
        page_count=page_count,
        embedding_status="processing",
        uploaded_by=uploaded_by_user_id,
    )
    session.add(document)
    session.flush()
    return document


def _populate_tsv(session: Session, document_id: int) -> None:
    bind = session.get_bind()
    if bind is None:
        return
    if bind.dialect.name == "postgresql":
        session.execute(
            text(
                "UPDATE chunks SET tsv = to_tsvector('english', text) "
                "WHERE document_id = :document_id"
            ),
            {"document_id": document_id},
        )
    else:
        session.execute(
            text("UPDATE chunks SET tsv = text WHERE document_id = :document_id"),
            {"document_id": document_id},
        )


def persist_ingested_document(
    session: Session,
    *,
    source_path: Path,
    extracted: ExtractedDocument,
    chunks: list[ChunkRecord],
    embeddings: list[list[float]],
    uploaded_by_user_id: int,
    document_id: int | None = None,
    doc_type: str | None = None,
    doc_code: str | None = None,
    title: str | None = None,
    source_locator: str | None = None,
) -> PipelineResult:
    existing_document = session.get(Document, document_id) if document_id is not None else None
    resolved_doc_type = doc_type or (existing_document.doc_type if existing_document is not None else infer_doc_type(source_path))
    resolved_doc_code = doc_code or (existing_document.doc_code if existing_document is not None else generate_doc_code(source_path, resolved_doc_type))
    resolved_title = title or (existing_document.title if existing_document is not None else extracted.title)
    # When the source came from object storage, keep the locator (s3://…) as source_path so the
    # worker can re-fetch on re-embed; otherwise stage the local file under upload_root as before.
    stored_source = source_locator if source_locator is not None else str(_staged_source_path(source_path, resolved_doc_code))
    document = _upsert_document(
        session,
        document_id=document_id,
        doc_code=resolved_doc_code,
        title=resolved_title,
        doc_type=resolved_doc_type,
        source_path=stored_source,
        page_count=len(extracted.pages),
        uploaded_by_user_id=uploaded_by_user_id,
    )

    if len(chunks) != len(embeddings):
        raise ValueError("Chunk count and embedding count must match.")

    for chunk, embedding in zip(chunks, embeddings, strict=True):
        session.add(
            Chunk(
                document_id=document.id,
                page=chunk.page,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                embedding=embedding,
            )
        )

    session.flush()
    _populate_tsv(session, document.id)

    document.chunk_count = len(chunks)
    document.page_count = len(extracted.pages)
    document.embedding_status = "ready"
    document.processed_at = datetime.now(UTC)
    document.error_message = None
    session.flush()

    return PipelineResult(
        document_id=document.id,
        doc_code=document.doc_code,
        page_count=document.page_count,
        chunk_count=document.chunk_count or 0,
        source_path=document.source_path,
    )


def run_ingestion_pipeline(
    document_path: str | Path,
    *,
    uploaded_by_user_id: int = 1,
    document_id: int | None = None,
    embedder: Callable[[list[str]], list[list[float]]] | None = None,
    session: Session | None = None,
    doc_type: str | None = None,
    doc_code: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    # `document_path` may be a storage locator (s3://bucket/key) when the worker processes an
    # uploaded document. Stage the bytes to a local temp file for extraction/OCR, and remember
    # the original locator so it is what gets recorded in documents.source_path.
    raw_path = str(document_path)
    source_locator: str | None = None
    if raw_path.startswith("s3://"):
        from backend.app.storage import stage_to_temp

        source_locator = raw_path
        suffix = Path(raw_path).suffix.lower()
        source_path = stage_to_temp(raw_path, suffix=suffix)
    else:
        source_path = Path(document_path)
        if not source_path.exists():
            raise FileNotFoundError(source_path)

    bootstrap_schema()
    extracted = extract_document(source_path)
    cleaned_pages = normalize_pages(extracted)
    resolved_doc_type = doc_type or infer_doc_type(source_path)
    resolved_doc_code = doc_code or generate_doc_code(source_path, resolved_doc_type)
    resolved_title = title or extracted.title
    chunks = chunk_document(
        cleaned_pages,
        doc_code=resolved_doc_code,
        title=resolved_title,
        doc_type=resolved_doc_type,
    )
    embeddings = (embedder or build_embeddings)([chunk.text for chunk in chunks])

    if session is not None:
        result = persist_ingested_document(
            session,
            source_path=source_path,
            extracted=ExtractedDocument(
                source_path=extracted.source_path,
                title=extracted.title,
                extension=extracted.extension,
                pages=cleaned_pages,
            ),
            chunks=chunks,
            embeddings=embeddings,
            uploaded_by_user_id=uploaded_by_user_id,
            document_id=document_id,
            doc_type=doc_type,
            doc_code=doc_code,
            title=title,
            source_locator=source_locator,
        )
        return asdict(result)

    with session_scope("writer") as db_session:
        result = persist_ingested_document(
            db_session,
            source_path=source_path,
            extracted=ExtractedDocument(
                source_path=extracted.source_path,
                title=extracted.title,
                extension=extracted.extension,
                pages=cleaned_pages,
            ),
            chunks=chunks,
            embeddings=embeddings,
            uploaded_by_user_id=uploaded_by_user_id,
            document_id=document_id,
            doc_type=doc_type,
            doc_code=doc_code,
            title=title,
            source_locator=source_locator,
        )
        return asdict(result)
