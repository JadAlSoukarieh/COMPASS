"""Document storage abstraction (MinIO/S3 + local backend)."""

from __future__ import annotations

from pathlib import Path

from backend.app.storage import LocalStorage, S3Storage


def test_local_storage_put_get_exists(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path / "docs"))
    locator = storage.put(key="POL-1.pdf", data=b"hello bytes")
    assert storage.exists(locator)
    assert storage.get(locator) == b"hello bytes"
    assert Path(locator).name == "POL-1.pdf"
    assert not storage.exists(str(tmp_path / "missing.pdf"))


def test_s3_locator_parsing() -> None:
    # _parse is pure string handling; no client/network needed.
    assert S3Storage._parse("s3://compass-documents/POL-1.pdf") == ("compass-documents", "POL-1.pdf")
    assert S3Storage._parse("s3://bucket/nested/key.docx") == ("bucket", "nested/key.docx")
