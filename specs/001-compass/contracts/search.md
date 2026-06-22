# Contract: Document Search

## POST /search
- **Auth**: required (all roles).
- **Body**: `{ "query": str, "analyze": bool }`
- **Behaviour**:
  - Input passes `input_guard()` (length cap, injection-pattern flag, rate limit) first.
  - Retrieval: keyword (FTS over tsv) + vector (pgvector cosine) → RRF fusion → cross-encoder rerank
    → top-k.
  - `analyze=false`: return ranked chunks only (no LLM).
  - `analyze=true`: pass top-k chunks (fenced as data) to the LLM for a grounded markdown answer with
    inline citations; `output_guard()` validates groundedness, citation validity (each citation maps
    to a retrieved chunk), and secret-pattern absence; weak evidence → refusal.
  - Cache: embedding cache (`emb:`), retrieval/answer cache (`search:<role>:<scope>:<mode>:<hash>`).
- **200 (analyze=false)**:
  ```json
  {
    "mode": "retrieval",
    "results": [
      { "chunk_id": int, "doc_code": str, "title": str, "page": int, "snippet": str, "score": float }
    ],
    "status_line": { "model": str, "retrieval": "hybrid", "reranked": true, "n_retrieved": int, "k_cited": 0, "latency_ms": int }
  }
  ```
- **200 (analyze=true)**:
  ```json
  {
    "mode": "answer",
    "answer_markdown": str,
    "citations": [ { "chunk_id": int, "doc_code": str, "page": int } ],
    "sources": [ { "chunk_id": int, "doc_code": str, "title": str, "page": int, "cited": bool, "text": str } ],
    "refused": false,
    "status_line": { "model": str, "retrieval": "hybrid", "reranked": true, "n_retrieved": int, "k_cited": int, "latency_ms": int }
  }
  ```
- Every search audit-logged (`action_type=doc_search`, detail: query, retrieved chunk_ids, k_cited,
  latency_ms, scope). Only `ready` documents are searchable.
