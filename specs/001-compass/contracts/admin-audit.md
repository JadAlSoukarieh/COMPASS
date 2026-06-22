# Contract: Manage Employees / Users & Audit Logs

Writes use the `compass_writer` DB role via explicitly-authorized endpoints (never the request-path
`compass_app` SELECT-only role).

## Manage Employees (hr, superuser)

### GET /employees
- **Auth**: `require_roles("hr","superuser")`. **200**: list of employees (HR scope).

### POST /employees
- **Auth**: `require_roles("hr","superuser")`. **Body**: employee fields. **201**: created employee.
- Busts related `dash:` cache keys. Audit-logged (`action_type=admin`).

### PATCH /employees/{id}
- **Auth**: `require_roles("hr","superuser")`. **200**: updated employee.
- Busts related `dash:` cache keys. Audit-logged (`action_type=admin`).

## Manage Users / Roles (superuser only)

### GET /users
- **Auth**: `require_roles("superuser")`. **200**: list of users with roles + is_active.

### POST /users  /  PATCH /users/{id}
- **Auth**: `require_roles("superuser")`. Create/edit/deactivate users; set role.
- Audit-logged (`action_type=admin`). Passwords hashed with bcrypt/passlib; never returned.

## Audit Logs

### GET /audit
- **Auth**: `require_roles("hr","superuser")`.
  - hr: HR-scope actions only. superuser: full.
- **Query**: `user_id?`, `action_type?`, `date_from?`, `date_to?`, pagination.
- **200**: list of `{ id, ts, user_id, role, action_type, detail (jsonb), result_status }`.
- The page renders the JSONB `detail` readably (question, intent, catalog_id, params, sources/chunk_ids,
  latency_ms, scope_decision, guardrail reason).
