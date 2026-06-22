import mimetypes
from pathlib import Path
import re
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.audit import write_audit
from backend.app.config import RuntimeSettings, get_settings
from backend.app.db import get_app_session, get_writer_session
from backend.app.models import Chunk, Document
from backend.app.schemas.documents import (
    DocumentListItem,
    DocumentPreviewChunkResponse,
    DocumentQueuedResponse,
    DocumentStatusResponse,
)
from backend.app.security.auth import AuthenticatedUser, get_current_user, require_roles
from backend.app.storage import get_storage, storage_for_locator
from worker.worker import enqueue_document_ingestion, get_queue

router = APIRouter(tags=["documents"])
templates = Jinja2Templates(directory="frontend/templates")

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".csv"}
ALLOWED_DOC_TYPES = {"policy", "howto"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")
SAFE_DOC_CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{1,63}$")


def _settings_from_request(request: Request) -> RuntimeSettings:
    return getattr(request.app.state, "settings", None) or get_settings()


def _queue_from_request(request: Request):
    return getattr(request.app.state, "ingestion_queue", None) or get_queue()


def _storage_from_request(request: Request):
    """Resolve document storage. Tests inject `app.state.storage` (or a local-only settings stub);
    in normal operation this returns the configured MinIO/S3 backend."""
    injected = getattr(request.app.state, "storage", None)
    if injected is not None:
        return injected
    state_settings = getattr(request.app.state, "settings", None)
    # A stubbed settings object that exposes only upload_root (no s3 fields) means local storage.
    if state_settings is not None and getattr(state_settings, "storage_backend", "local") != "s3":
        from backend.app.storage import LocalStorage

        return LocalStorage(state_settings.upload_root)
    return get_storage()


def _validate_filename(filename: str | None) -> str:
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename is required.")
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsafe filename.")
    if not SAFE_FILENAME_RE.fullmatch(filename):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Filename failed validation.")
    return filename


def _validate_doc_code(doc_code: str) -> str:
    normalized = doc_code.strip().upper()
    if not SAFE_DOC_CODE_RE.fullmatch(normalized):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid document code.")
    return normalized


def _validate_title(title: str) -> str:
    normalized = " ".join(title.split()).strip()
    if not normalized:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title is required.")
    if len(normalized) > 255:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title is too long.")
    return normalized


def _validate_doc_type(doc_type: str) -> Literal["policy", "howto"]:
    normalized = doc_type.strip().lower()
    if normalized not in ALLOWED_DOC_TYPES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid document type.")
    return normalized  # type: ignore[return-value]


def _store_upload(*, request: Request, doc_code: str, filename: str, payload: bytes) -> str:
    """Validate and persist the upload to document storage (MinIO/S3 or local).

    Returns the storage locator recorded in documents.source_path
    (``s3://bucket/key`` for object storage, or an absolute path for local).
    """
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported file type.")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File is too large.")

    return _storage_from_request(request).put(key=f"{doc_code}{suffix}", data=payload)


@router.get("/manage-documents", response_class=HTMLResponse)
def manage_documents_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="manage_documents.html",
        context={"page_title": "Manage Documents · Compass"},
    )


@router.post("/documents", response_model=DocumentQueuedResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    doc_code: str = Form(...),
    title: str = Form(...),
    doc_type: str = Form(...),
    current_user: AuthenticatedUser = Depends(require_roles("hr", "superuser")),
    session: Session = Depends(get_writer_session),
) -> DocumentQueuedResponse:
    filename = _validate_filename(file.filename)
    normalized_doc_code = _validate_doc_code(doc_code)
    normalized_title = _validate_title(title)
    normalized_doc_type = _validate_doc_type(doc_type)

    existing = session.scalar(select(Document).where(Document.doc_code == normalized_doc_code))
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Document code already exists.")

    payload = await file.read()
    stored_locator = _store_upload(request=request, doc_code=normalized_doc_code, filename=filename, payload=payload)

    document = Document(
        doc_code=normalized_doc_code,
        title=normalized_title,
        doc_type=normalized_doc_type,
        source_path=stored_locator,
        page_count=0,
        embedding_status="pending",
        uploaded_by=current_user.user_id,
    )
    session.add(document)
    session.flush()

    queue = _queue_from_request(request)
    try:
        enqueue_document_ingestion(
            document_id=document.id,
            source_path=document.source_path,
            uploaded_by_user_id=current_user.user_id,
            doc_type=document.doc_type,
            queue=queue,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not enqueue ingestion job.") from exc
    write_audit(
        action_type="admin",
        role=current_user.role.value,
        result_status="success",
        user_id=current_user.user_id,
        session=session,
        detail={
            "operation": "upload_document",
            "document_id": document.id,
            "doc_code": document.doc_code,
            "doc_type": document.doc_type,
            "filename": filename,
        },
    )
    return DocumentQueuedResponse(document_id=document.id, embedding_status="pending")


@router.get("/documents", response_model=list[DocumentListItem], status_code=status.HTTP_200_OK)
def list_documents(
    current_user: AuthenticatedUser = Depends(require_roles("hr", "superuser")),
    session: Session = Depends(get_app_session),
) -> list[DocumentListItem]:
    documents = session.scalars(
        select(Document).order_by(Document.uploaded_at.desc(), Document.id.desc())
    ).all()
    return [
        DocumentListItem(
            id=document.id,
            doc_code=document.doc_code,
            title=document.title,
            doc_type=document.doc_type,
            embedding_status=document.embedding_status,
            chunk_count=document.chunk_count,
            uploaded_at=document.uploaded_at,
            processed_at=document.processed_at,
            error_message=document.error_message,
        )
        for document in documents
    ]


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse, status_code=status.HTTP_200_OK)
def document_status(
    document_id: int,
    current_user: AuthenticatedUser = Depends(require_roles("hr", "superuser")),
    session: Session = Depends(get_app_session),
) -> DocumentStatusResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return DocumentStatusResponse(
        document_id=document.id,
        embedding_status=document.embedding_status,
        chunk_count=document.chunk_count,
        error_message=document.error_message,
    )


@router.get("/documents/{document_id}/preview", response_class=HTMLResponse)
def document_preview_page(
    document_id: int,
    request: Request,
    session: Session = Depends(get_app_session),
) -> HTMLResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return templates.TemplateResponse(
        request=request,
        name="document_preview.html",
        context={"page_title": f"{document.doc_code} · Preview", "document_id": document.id},
    )


@router.get(
    "/documents/{document_id}/chunks/{chunk_id}",
    response_model=DocumentPreviewChunkResponse,
    status_code=status.HTTP_200_OK,
)
def document_chunk_preview(
    document_id: int,
    chunk_id: int,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_app_session),
) -> DocumentPreviewChunkResponse:
    chunk = session.scalar(
        select(Chunk)
        .join(Document, Document.id == Chunk.document_id)
        .where(Chunk.id == chunk_id, Chunk.document_id == document_id)
    )
    if chunk is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chunk not found for document.")
    document = chunk.document
    return DocumentPreviewChunkResponse(
        document_id=document.id,
        doc_code=document.doc_code,
        title=document.title,
        page=chunk.page,
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        text=chunk.text,
    )


@router.get("/documents/{document_id}/file")
def document_file(
    document_id: int,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: Session = Depends(get_app_session),
) -> Response:
    """Serve the original source file for preview/download.

    Available to any authenticated user (document search itself is open to all roles, and the
    retrieved chunk text is already shown). Bytes are streamed from object storage (MinIO/S3).
    Inline disposition lets the browser preview PDFs; Office files download.
    """
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    # Dispatch by the stored locator's scheme (corpus is mixed: CLI=local paths, uploads=s3://),
    # unless a test injected a storage stub on app.state.
    injected = getattr(request.app.state, "storage", None)
    storage = injected if injected is not None else storage_for_locator(document.source_path)
    if not storage.exists(document.source_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file missing for document.")

    data = storage.get(document.source_path)
    suffix = Path(document.source_path).suffix.lower()
    content_type = mimetypes.types_map.get(suffix, "application/octet-stream")
    # PDFs preview inline in-browser; other types download with a clean filename.
    disposition = "inline" if suffix == ".pdf" else "attachment"
    filename = f"{document.doc_code}{suffix}"

    write_audit(
        action_type="doc_search",
        role=current_user.role.value,
        result_status="success",
        user_id=current_user.user_id,
        session=session,
        detail={"operation": "document_preview", "document_id": document.id, "doc_code": document.doc_code},
    )
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.post("/documents/{document_id}/reembed", response_model=DocumentQueuedResponse, status_code=status.HTTP_202_ACCEPTED)
def reembed_document(
    request: Request,
    document_id: int,
    current_user: AuthenticatedUser = Depends(require_roles("hr", "superuser")),
    session: Session = Depends(get_writer_session),
) -> DocumentQueuedResponse:
    document = session.get(Document, document_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    if not _storage_from_request(request).exists(document.source_path):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stored file missing for document.")

    session.execute(delete(Chunk).where(Chunk.document_id == document_id))
    document.embedding_status = "pending"
    document.error_message = None
    document.chunk_count = None
    document.processed_at = None
    session.flush()

    enqueue_document_ingestion(
        document_id=document.id,
        source_path=document.source_path,
        uploaded_by_user_id=document.uploaded_by,
        doc_type=document.doc_type,
        queue=_queue_from_request(request),
    )
    write_audit(
        action_type="admin",
        role=current_user.role.value,
        result_status="success",
        user_id=current_user.user_id,
        session=session,
        detail={
            "operation": "reembed_document",
            "document_id": document.id,
            "doc_code": document.doc_code,
        },
    )
    return DocumentQueuedResponse(document_id=document.id, embedding_status="pending")
