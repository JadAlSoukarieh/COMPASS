from __future__ import annotations

from pathlib import Path

import pytest

from ingestion.chunk import chunk_document, estimate_tokens
from ingestion.clean import clean_text
from ingestion.extract import (
    ExtractedDocument,
    ExtractedPage,
    extract_document,
    extract_pdf_document,
    should_ocr_pdf,
)
from ingestion.pipeline import persist_ingested_document, run_ingestion_pipeline


def test_clean_text_normalizes_page_noise() -> None:
    raw = "Page 2\n• Policy updat-\ned\x00 text\n\n\n3\n"
    assert clean_text(raw) == "- Policy updated text"


def test_chunk_document_preserves_overlap_and_boundaries() -> None:
    pages = [
        ExtractedPage(page_number=1, text="\n\n".join([f"Paragraph {index} " + "word " * 80 for index in range(1, 6)])),
    ]

    chunks = chunk_document(
        pages,
        doc_code="DOC-TEST",
        title="Test Doc",
        doc_type="reference",
        target_tokens=140,
        overlap_tokens=20,
    )

    assert len(chunks) >= 2
    assert all(chunk.page == 1 for chunk in chunks)
    assert all(estimate_tokens(chunk.text) <= 160 for chunk in chunks)

    previous_tail = chunks[0].text.split()[-20:]
    next_head = chunks[1].text.split()[:20]
    assert previous_tail == next_head


def test_extract_document_dispatches_text_file(tmp_path: Path) -> None:
    source = tmp_path / "leave-policy.txt"
    source.write_text("Line one\n\nLine two", encoding="utf-8")

    extracted = extract_document(source)

    assert extracted.title == "leave-policy"
    assert extracted.pages[0].text == "Line one\n\nLine two"


def test_should_ocr_pdf_only_when_no_text_layer() -> None:
    assert should_ocr_pdf([ExtractedPage(page_number=1, text=""), ExtractedPage(page_number=2, text=" ")]) is True
    assert should_ocr_pdf([ExtractedPage(page_number=1, text="found text but quite long here")]) is False


def test_page_needs_ocr_checker() -> None:
    from ingestion.extract import page_needs_ocr

    assert page_needs_ocr("") is True
    assert page_needs_ocr("   \n  ") is True
    assert page_needs_ocr("a few words") is True  # below the min-chars threshold
    assert page_needs_ocr("This page has a substantial, real text layer extracted from the PDF.") is False


def test_extract_pdf_document_ocrs_only_image_pages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "mixed.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test")

    # Page 1 has a real text layer; page 2 is image-only (empty) and must be OCR'd; page 3 is fine.
    monkeypatch.setattr(
        "ingestion.extract.extract_pdf_text_pages",
        lambda path: [
            ExtractedPage(page_number=1, text="Page one has plenty of extracted text content.", source_kind="text"),
            ExtractedPage(page_number=2, text="", source_kind="text"),
            ExtractedPage(page_number=3, text="Page three also has a normal extracted text layer.", source_kind="text"),
        ],
    )

    ocr_calls: list[list[int]] = []

    def fake_ocr(path, page_numbers):
        ocr_calls.append(list(page_numbers))
        return {n: "OCR content for scanned page" for n in page_numbers}

    monkeypatch.setattr("ingestion.extract.ocr_specific_pages", fake_ocr)

    extracted = extract_pdf_document(pdf_path)

    # Only page 2 should have been OCR'd — not the whole document.
    assert ocr_calls == [[2]]
    assert extracted.pages[1].source_kind == "ocr"
    assert extracted.pages[1].text == "OCR content for scanned page"
    assert extracted.pages[0].source_kind == "text"
    assert extracted.pages[2].source_kind == "text"


def test_run_ingestion_pipeline_persists_chunks_with_injected_embedder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "policy.txt"
    source.write_text("Paragraph one.\n\nParagraph two.", encoding="utf-8")

    class FakeSession:
        def __init__(self) -> None:
            self.added = []
            self.executed = []
            self.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "sqlite"})()})()
            self.document = None

        def add(self, item):
            if item.__class__.__name__ == "Document" and self.document is None:
                item.id = 7
                self.document = item
            self.added.append(item)

        def flush(self):
            return None

        def execute(self, statement, params=None):
            self.executed.append((str(statement), params))
            return None

        def get(self, model, document_id):
            return self.document if self.document and document_id == self.document.id else None

        def get_bind(self):
            return self.bind

    fake_session = FakeSession()
    monkeypatch.setattr("ingestion.pipeline.bootstrap_schema", lambda: None)
    monkeypatch.setattr(
        "ingestion.pipeline._staged_source_path",
        lambda source_path, doc_code: tmp_path / f"{doc_code}{source_path.suffix}",
    )

    result = run_ingestion_pipeline(
        source,
        session=fake_session,
        embedder=lambda texts: [[0.1] * 1536 for _ in texts],
        uploaded_by_user_id=1,
    )

    assert result["document_id"] == 7
    assert result["chunk_count"] >= 1
    assert any(item.__class__.__name__ == "Chunk" for item in fake_session.added)


def test_persist_ingested_document_records_document_and_chunks(tmp_path: Path) -> None:
    source = tmp_path / "policy.txt"
    source.write_text("Policy line", encoding="utf-8")

    extracted = ExtractedDocument(
        source_path=source,
        title="policy",
        extension=".txt",
        pages=[ExtractedPage(page_number=1, text="Policy line")],
    )

    chunks = [
        type(
            "ChunkLike",
            (),
            {
                "page": 1,
                "chunk_index": 0,
                "text": "Policy line",
            },
        )()
    ]

    class FakeSession:
        def __init__(self) -> None:
            self.added = []
            self.executed = []
            self.bind = type("Bind", (), {"dialect": type("Dialect", (), {"name": "sqlite"})()})()
            self.document = None

        def add(self, item):
            if item.__class__.__name__ == "Document" and self.document is None:
                item.id = 42
                self.document = item
            self.added.append(item)

        def flush(self):
            return None

        def execute(self, statement, params=None):
            self.executed.append((str(statement), params))
            return None

        def get(self, model, document_id):
            return None

        def get_bind(self):
            return self.bind

    session = FakeSession()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "ingestion.pipeline._staged_source_path",
        lambda source_path, doc_code: tmp_path / f"{doc_code}{source_path.suffix}",
    )
    result = persist_ingested_document(
        session,
        source_path=source,
        extracted=extracted,
        chunks=chunks,
        embeddings=[[0.2] * 1536],
        uploaded_by_user_id=1,
    )

    assert result.document_id == 42
    assert result.chunk_count == 1
    assert any("UPDATE chunks SET tsv = text" in statement for statement, _ in session.executed)
    monkeypatch.undo()
