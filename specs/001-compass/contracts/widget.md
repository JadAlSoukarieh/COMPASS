# Contract: Chat Widget (intent → data_query / data_analysis / app_support / refuse)

The LLM never writes or sees SQL. It returns only structured selections; the backend validates,
enforces role/scope, and executes pre-written parameterized queries.

## POST /widget/message
- **Auth**: required (all roles).
- **Body**: `{ "message": str, "context": { "page": str|null, "dashboard_id": str|null } }`
- **Flow**:
  1. `input_guard()` on the message.
  2. **Intent routing** (rule-based first, LLM fallback) → `data_query | data_analysis | app_support | refuse`. Logged.
  3. Branch:
     - **data_query (6a)**: LLM returns `{ "catalog_id": str, "params": {...} }` (strict JSON,
       `output_guard()` schema-validated). Backend validates `catalog_id` ∈ registry and each param
       vs schema; resolves scope from JWT; if out of scope → refuse. Runs the bound parameterized
       query via the least-privilege `compass_app` role. LLM then phrases the rows in plain language.
     - **data_analysis (6b)**: backend runs the relevant scoped catalog query(ies) for the dashboard,
       passes only those rows (fenced as data) to the LLM with an analysis prompt; returns a written
       summary. The LLM never fetches data itself.
     - **app_support (6c)**: answered from the app-help corpus via the same RAG path as /search.
     - **refuse**: clean refusal.
  4. `output_guard()` on the final text.
- **200**:
  ```json
  {
    "intent": "data_query|data_analysis|app_support|refuse",
    "answer_markdown": str,
    "catalog_id": str|null,
    "used_params": { },
    "scope_decision": "allowed|scoped|refused",
    "sources": [ ],
    "refused": false
  }
  ```
- Audit-logged per intent (`data_query` / `data_analysis` / `support`) with intent, catalog_id,
  params, scope_decision, latency_ms; guardrail trips logged as `guardrail_block`.

## Hard rules (Constitution II–V)
- LLM output for data_query is ONLY `{catalog_id, params}` — rejected if it is not valid JSON or the
  id is not in the registry or a param fails schema validation. Never `eval`'d.
- The catalog `sql` field and table names are never placed in any prompt.
- Scope comes from the JWT, never from the message or the model.
