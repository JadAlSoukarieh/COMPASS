# Contract: Manage Documents (async ingestion)

Role: hr, superuser only. Uploads enqueue an async RQ job; ingestion never runs in the request.

## POST /documents (upload)
- **Auth**: `require_roles("hr","superuser")`.
- **Body**: multipart — file + `{ "doc_code": str, "title": str, "doc_type": "policy|howto" }`.
- **Validation**: type allowlist (pdf/docx/xlsx/csv), max size, filename scan; stored outside web root.
- **Behaviour**: save file → create `documents` row (`embedding_status="pending"`) → enqueue RQ
  ingestion job → return immediately.
- **202**: `{ "document_id": int, "embedding_status": "pending" }`.
- Audit-logged (`action_type=admin`).

## GET /documents
- **Auth**: `require_roles("hr","superuser")`.
- **200**: list of `{ id, doc_code, title, doc_type, embedding_status, chunk_count, uploaded_at, processed_at, error_message }`.
- Drives the per-document status badges (Pending/Processing/Ready/Failed).

## GET /documents/{id}/status
- **Auth**: `require_roles("hr","superuser")`.
- **200**: `{ "document_id": int, "embedding_status": str, "chunk_count": int|null, "error_message": str|null }`.
- Polled by the UI for live status.

## POST /documents/{id}/reembed
- **Auth**: `require_roles("hr","superuser")`.
- **Behaviour**: re-enqueue the ingestion job for an existing doc (retry failed or re-embed ready);
  clears prior chunks for that doc, resets status to pending.
- **202**: `{ "document_id": int, "embedding_status": "pending" }`.
- Audit-logged (`action_type=admin`).

## Worker status machine (RQ)
`pending → processing → ready` (sets chunk_count, processed_at) | `→ failed` (sets error_message).
Worker calls the shared `ingestion.pipeline` module (same as the CLI). Jobs retryable.
A document is searchable only when `ready`.
