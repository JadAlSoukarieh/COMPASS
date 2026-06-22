# Data Model: Compass

Derived from brief sections 5, 7, and 9b. All synthetic. Schema is illustrative — add columns as
needed, but the relationships, the embedding/status fields, and the audit detail JSONB are required.

## Database tables (PostgreSQL + pgvector)

### users
| column | type | notes |
|---|---|---|
| id | serial PK | |
| username | text unique | |
| password_hash | text | bcrypt/passlib |
| role | text | one of: superuser, hr, mgr, emp |
| employee_id | int FK→employees.id, nullable | links a login to an employee record |
| is_active | bool | deactivation = soft disable |

### employees
| column | type | notes |
|---|---|---|
| id | serial PK | |
| full_name | text | |
| department | text | |
| grade | text/int | grade/level |
| manager_id | int FK→employees.id, nullable | self-FK builds the hierarchy |
| hire_date | date | tenure base |
| contract_end_date | date, nullable | for expiring-contract queries |
| salary | numeric | salary distribution queries |
| status | text | active / left / on_leave etc. |

### leave_balances
| column | type | notes |
|---|---|---|
| employee_id | int FK→employees.id | |
| leave_type | text | annual / sick / unpaid |
| days_total | numeric | |
| days_used | numeric | remaining = total − used |
| year | int | |

### leave_requests
| column | type | notes |
|---|---|---|
| id | serial PK | |
| employee_id | int FK→employees.id | |
| start_date | date | |
| end_date | date | |
| type | text | annual / sick / unpaid |
| status | text | pending / approved / rejected |
| approver_id | int FK→employees.id, nullable | for approval-bottleneck queries |

### documents
| column | type | notes |
|---|---|---|
| id | serial PK | |
| doc_code | text | invented code, e.g. HR-POL-014 |
| title | text | |
| doc_type | text | policy / howto |
| source_path | text | stored outside web root |
| page_count | int | |
| embedding_status | text | pending / processing / ready / failed |
| uploaded_by | int FK→users.id | |
| uploaded_at | timestamptz | |
| processed_at | timestamptz, nullable | |
| error_message | text, nullable | exception on failure |
| chunk_count | int, nullable | set on success |

### chunks
| column | type | notes |
|---|---|---|
| id | serial PK | |
| document_id | int FK→documents.id | |
| page | int | preserved from extraction |
| chunk_index | int | order within document |
| text | text | cleaned chunk text |
| embedding | vector(1536) | OpenAI text-embedding-3-small |
| tsv | tsvector | to_tsvector for FTS |

Indexes: GIN on `chunks.tsv`; HNSW (or IVFFlat) on `chunks.embedding` (cosine).

### audit_log
| column | type | notes |
|---|---|---|
| id | serial PK | |
| ts | timestamptz | |
| user_id | int FK→users.id, nullable | nullable for failed logins |
| role | text | snapshot at action time |
| action_type | text | login / doc_search / data_query / data_analysis / support / admin / guardrail_block |
| detail | jsonb | question, intent, catalog_id, params, sources/chunk_ids, latency_ms, scope_decision, reason |
| result_status | text | success / refused / blocked / error |

## Database roles (least privilege)

- `compass_app` — SELECT on the catalog's read tables + INSERT into `audit_log`; **no** DROP/ALTER/
  DELETE/UPDATE. Used by the request path for catalog query execution.
- `compass_writer` — limited write access used only by explicitly-authorized admin endpoints
  (manage employees/users, document rows, chunk inserts during ingestion).

## SQL Catalog registry (not a DB table)

A Python registry (dataclasses or YAML/JSON loaded at startup). Each entry:

```
id:            EMP_LEAVE_BALANCE
description:   "Remaining leave days for a specific employee, by leave type"
params:        { employee_id: int }            # schema: type, range, allowed values, existence
required_role: ["hr", "superuser"]             # or governed by scope
scope:         self | team | company           # how the requesting user's scope is applied
sql:           <parameterized query, bind params only>   # NEVER shown to the LLM
formatter:     optional answer template
```

The LLM is given only `id`, `description`, `params`. The backend validates `catalog_id` against the
registry and each param against its schema, applies scope from the JWT, then executes the bound query.

### Target catalog entries (~15–20, spanning categories)

**Self-scope (emp on self):**
1. `EMP_LEAVE_BALANCE` — my leave balance by type.
2. `EMP_LEAVE_HISTORY` — my leave request history & status.
3. `EMP_TENURE` — my contract end date & tenure.
4. `EMP_UPCOMING_LEAVE` — my upcoming approved leave.

**Team-scope (mgr, direct reports):**
5. `TEAM_HEADCOUNT_BY_GRADE` — team headcount by grade/role.
6. `TEAM_ON_LEAVE_PERIOD` — who is on leave this week / next month.
7. `TEAM_PENDING_MY_APPROVAL` — reports with pending requests awaiting my approval.
8. `TEAM_PROBATION_ENDING` — team members approaching probation end.
9. `TEAM_BURNOUT_SIGNAL` — members with no leave taken in last N months.
10. `TEAM_CARRYOVER_RISK` — team leave-balance summary (who risks losing carry-over).
11. `TEAM_TENURE_DISTRIBUTION` — team tenure distribution.

**Company-scope (hr/superuser):**
12. `CO_SALARY_DISTRIBUTION` — salary distribution by department and grade.
13. `CO_HEADCOUNT_BY_DEPT` — headcount by department.
14. `CO_GENDER_GRADE_BREAKDOWN` — gender/grade headcount breakdown.
15. `CO_CONTRACTS_EXPIRING` — contracts expiring in next N days.
16. `CO_NEW_HIRES` — new hires in last N days.
17. `CO_TURNOVER` — leavers over a date range.
18. `CO_APPROVAL_BACKLOG_BY_DEPT` — departments with highest pending-approval backlog.
19. `CO_AVG_TENURE_BY_DEPT` — average tenure by department.
20. `CO_LEAVE_UTILIZATION_BY_DEPT` — leave utilization rate by department.

**Cross-cutting signal (hr/mgr):**
21. `SIG_APPROVAL_BOTTLENECK` — approver with most pending + longest avg wait.
22. `SIG_OVERDUE_APPROVALS` — pending beyond X days.

(Pick 15–20 of the above for the first build; the list provides headroom and variety.)

## LLM structured-output schemas

- **Intent classification** → `{ "intent": "data_query" | "data_analysis" | "app_support" | "refuse" }`.
- **Catalog selection** → `{ "catalog_id": "<from registry>", "params": { ... } }` — validated against
  the registry and the entry's param schema; malformed → reject/repair, never executed.
- **Grounded answer** (RAG) → markdown answer + citations that MUST map to retrieved chunk ids.

## Cache key namespaces (Redis)

- `emb:<model>:<sha256(normalized_query)>` → query embedding (long TTL).
- `search:<role>:<scope>:<mode>:<sha256(query)>` → retrieval/answer result (short TTL, 5–15 min).
- `dash:<catalog_id>:<scope>:<sha256(params)>` → dashboard rows (short TTL, 60–120 s; busted on writes).

Permission-sensitive keys ALWAYS include role/scope. Never cache another user's data under a key a
different user could hit.
