from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Callable

from redis import Redis
from rq import Queue, Retry, Worker
from sqlalchemy import delete

from backend.app.config import get_settings
from backend.app.db import session_scope
from backend.app.models import Chunk, Document
from backend.app.retrieval import preload_reranker
from ingestion.pipeline import run_ingestion_pipeline

QUEUE_NAMES = ("default", "ingestion")
INGESTION_QUEUE_NAME = "ingestion"
INGESTION_JOB_TIMEOUT_SECONDS = 900


def get_redis_connection() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url)


def get_queue(name: str = INGESTION_QUEUE_NAME, connection: Redis | None = None) -> Queue:
    return Queue(name, connection=connection or get_redis_connection())


def build_worker(connection: Redis | None = None) -> Worker:
    active_connection = connection or get_redis_connection()
    queues = [Queue(name, connection=active_connection) for name in QUEUE_NAMES]
    return Worker(queues, connection=active_connection)


def _mark_processing(document_id: int, *, session) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document {document_id} not found.")
    document.embedding_status = "processing"
    document.error_message = None
    session.flush()
    return document


def _mark_failed(document_id: int, error_message: str, *, session) -> None:
    document = session.get(Document, document_id)
    if document is None:
        raise ValueError(f"Document {document_id} not found.")
    document.embedding_status = "failed"
    document.error_message = error_message
    document.processed_at = None
    session.flush()


def process_document_ingestion(
    *,
    document_id: int,
    source_path: str,
    uploaded_by_user_id: int,
    doc_type: str | None = None,
    embedder: Callable[[list[str]], list[list[float]]] | None = None,
) -> dict[str, Any]:
    with session_scope("writer") as session:
        _mark_processing(document_id, session=session)

    try:
        with session_scope("writer") as session:
            return run_ingestion_pipeline(
                source_path,
                uploaded_by_user_id=uploaded_by_user_id,
                document_id=document_id,
                embedder=embedder,
                session=session,
                doc_type=doc_type,
            )
    except Exception as exc:
        with session_scope("writer") as session:
            _mark_failed(document_id, str(exc), session=session)
        raise


def enqueue_document_ingestion(
    *,
    document_id: int,
    source_path: str,
    uploaded_by_user_id: int,
    doc_type: str | None = None,
    queue: Queue | None = None,
) -> Any:
    active_queue = queue or get_queue()
    return active_queue.enqueue(
        process_document_ingestion,
        document_id=document_id,
        source_path=source_path,
        uploaded_by_user_id=uploaded_by_user_id,
        doc_type=doc_type,
        retry=Retry(max=2, interval=[10, 30]),
        job_timeout=INGESTION_JOB_TIMEOUT_SECONDS,
    )


def reembed_document_ingestion(
    *,
    document_id: int,
    source_path: str,
    uploaded_by_user_id: int,
    doc_type: str | None = None,
    queue: Queue | None = None,
) -> Any:
    with session_scope("writer") as session:
        document = session.get(Document, document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found.")
        session.execute(delete(Chunk).where(Chunk.document_id == document_id))
        document.embedding_status = "pending"
        document.error_message = None
        document.chunk_count = None
        document.processed_at = None
        session.flush()

    return enqueue_document_ingestion(
        document_id=document_id,
        source_path=source_path,
        uploaded_by_user_id=uploaded_by_user_id,
        doc_type=doc_type,
        queue=queue,
    )


def worker_healthcheck() -> None:
    """Healthcheck that fails if Redis is down OR no live RQ worker is consuming the queues.

    The previous version only pinged Redis, so a crashed RQ worker (e.g. after a Redis timeout)
    still reported healthy while jobs piled up unprocessed. We now also require at least one RQ
    worker whose heartbeat is recent.
    """
    connection = get_redis_connection()
    if not connection.ping():
        raise SystemExit(1)

    from datetime import datetime, timezone

    workers = Worker.all(connection=connection)
    if not workers:
        raise SystemExit(1)

    now = datetime.now(timezone.utc)
    for worker in workers:
        last_beat = getattr(worker, "last_heartbeat", None)
        if last_beat is None:
            continue
        if last_beat.tzinfo is None:
            last_beat = last_beat.replace(tzinfo=timezone.utc)
        # RQ default worker TTL is 420s; treat a heartbeat within 120s as alive.
        if (now - last_beat).total_seconds() < 120:
            return
    raise SystemExit(1)


def main() -> None:
    settings = get_settings()
    preload_reranker(settings.reranker_model, async_load=True)
    connection = get_redis_connection()
    worker = build_worker(connection)
    worker.work()


if __name__ == "__main__":
    main()
