from __future__ import annotations

import argparse
from pathlib import Path

from ingestion.extract import SUPPORTED_EXTENSIONS
from ingestion.pipeline import run_ingestion_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Compass document ingestion.")
    parser.add_argument("document_path", nargs="?", default="data/docs", help="Path to a file or directory to ingest.")
    parser.add_argument("--uploaded-by", type=int, default=1, help="User id recorded as the uploader.")
    return parser


def _iter_documents(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_EXTENSIONS
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    path = Path(args.document_path)
    for candidate in _iter_documents(path):
        run_ingestion_pipeline(candidate, uploaded_by_user_id=args.uploaded_by)


if __name__ == "__main__":
    main()
