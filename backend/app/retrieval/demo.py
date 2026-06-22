from __future__ import annotations

import argparse
import json

from backend.app.retrieval import search


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a Compass retrieval query against the live corpus.")
    parser.add_argument("query", help="Natural-language document search query.")
    parser.add_argument("--top-k", type=int, default=5, dest="top_k", help="Number of reranked results to return.")
    parser.add_argument(
        "--candidate-limit",
        type=int,
        default=20,
        dest="candidate_limit",
        help="Number of hybrid candidates to fuse before reranking.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    results = search(
        args.query,
        top_k=args.top_k,
        candidate_limit=args.candidate_limit,
    )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
