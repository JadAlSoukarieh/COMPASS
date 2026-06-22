"""Document object storage abstraction.

Uploaded documents are stored in MinIO (S3-compatible object storage) so files live outside
the web root and outside the app/worker containers (brief §9b/§12e). The same module exposes a
local-filesystem backend used as a fallback for tests and offline CLI runs.

Storage keys mirror the prior convention: ``<doc_code><suffix>`` (e.g. ``POL-LEAVE-2026.pdf``).
The ``documents.source_path`` column stores ``s3://<bucket>/<key>`` for object storage or an
absolute filesystem path for the local backend, so the ingestion worker can fetch the bytes back.
"""

from __future__ import annotations

import logging
import shutil
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from backend.app.config import get_settings

logger = logging.getLogger(__name__)


class DocumentStorage(Protocol):
    def put(self, *, key: str, data: bytes) -> str:
        """Store bytes under key; return a locator stored in documents.source_path."""

    def get(self, locator: str) -> bytes:
        """Fetch bytes for a locator produced by put()."""

    def exists(self, locator: str) -> bool:
        ...


class LocalStorage:
    """Filesystem backend (outside the web root). Used for tests / CLI / no-MinIO mode."""

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    def put(self, *, key: str, data: bytes) -> str:
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / key
        destination.write_bytes(data)
        return str(destination)

    def get(self, locator: str) -> bytes:
        return Path(locator).read_bytes()

    def exists(self, locator: str) -> bool:
        return Path(locator).exists()

    def stage_local(self, locator: str, *, suffix: str) -> Path:
        # Already on the local filesystem; no copy needed.
        return Path(locator)


class S3Storage:
    """MinIO / S3 backend via boto3."""

    def __init__(self, *, endpoint_url: str, access_key: str, secret_key: str, bucket: str, region: str = "us-east-1") -> None:
        import boto3
        from botocore.client import Config as BotoConfig

        self.bucket = bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=BotoConfig(signature_version="s3v4"),
        )
        self._ensure_bucket()

    def _ensure_bucket(self) -> None:
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self._client.create_bucket(Bucket=self.bucket)
            except ClientError as exc:  # pragma: no cover - race / perms
                logger.warning("Could not create bucket %s: %s", self.bucket, exc.__class__.__name__)

    @staticmethod
    def _parse(locator: str) -> tuple[str, str]:
        # s3://bucket/key
        without_scheme = locator.removeprefix("s3://")
        bucket, _, key = without_scheme.partition("/")
        return bucket, key

    def put(self, *, key: str, data: bytes) -> str:
        self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return f"s3://{self.bucket}/{key}"

    def get(self, locator: str) -> bytes:
        bucket, key = self._parse(locator)
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def exists(self, locator: str) -> bool:
        from botocore.exceptions import ClientError

        bucket, key = self._parse(locator)
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError:
            return False


@lru_cache(maxsize=1)
def get_storage() -> DocumentStorage:
    settings = get_settings()
    if getattr(settings, "storage_backend", "local") == "s3":
        return S3Storage(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key.get_secret_value(),
            secret_key=settings.s3_secret_key.get_secret_value(),
            bucket=settings.s3_bucket,
        )
    return LocalStorage(settings.upload_root)


def storage_for_locator(locator: str) -> DocumentStorage:
    """Pick the right backend for an existing source_path.

    The corpus can be mixed: CLI batch ingestion writes local paths, while uploads write
    s3:// locators. Dispatch on the scheme so a local-path document still reads correctly even
    when the configured default backend is S3 (and vice versa).
    """
    if str(locator).startswith("s3://"):
        configured = get_storage()
        if isinstance(configured, S3Storage):
            return configured
        # Default is local but we have an s3 locator → build an S3 client from settings.
        settings = get_settings()
        return S3Storage(
            endpoint_url=settings.s3_endpoint_url,
            access_key=settings.s3_access_key.get_secret_value(),
            secret_key=settings.s3_secret_key.get_secret_value(),
            bucket=settings.s3_bucket,
        )
    return LocalStorage(get_settings().upload_root)


def stage_to_temp(locator: str, *, suffix: str) -> Path:
    """Return a local filesystem path with the document bytes, fetching from storage if needed.

    Ingestion (extract/OCR) needs a real file path. For the local backend the locator already is
    a path; for S3 we download to a temp file.
    """
    storage = storage_for_locator(locator)
    if isinstance(storage, LocalStorage) and Path(locator).exists():
        return Path(locator)

    import tempfile

    data = storage.get(locator)
    tmp = tempfile.NamedTemporaryFile(prefix="compass_ingest_", suffix=suffix, delete=False)
    tmp.write(data)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)
